"""Main scan loop: whales -> discovery -> filters -> safety/social -> score -> alert -> track outcomes."""

from __future__ import annotations

import logging
import time
from collections import defaultdict

from . import safety as safety_mod
from . import socials as socials_mod
from .alerts import Alerter, money
from .config import Config
from .dexscreener import DexScreener, Pair
from .http import HttpClient
from .scoring import Signal, build_signal, early_score, hard_filter, momentum_score
from .store import Store
from .whales import EvmTracker, SolanaTracker, WhaleTrade

log = logging.getLogger(__name__)

CACHE_TTL = 30 * 60  # seconds to cache safety / social results per token


class Bot:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.http = HttpClient()
        self.dex = DexScreener(self.http)
        self.store = Store(cfg.database_path)
        self.alerter = Alerter(self.http, cfg.secrets.telegram_bot_token, cfg.secrets.telegram_chat_id)
        self.sol = SolanaTracker(self.http, cfg.secrets.solana_rpc_url)
        self.evm = EvmTracker(self.http, cfg.secrets.etherscan_api_key)
        self._safety_cache: dict[tuple[str, str], tuple[float, safety_mod.SafetyReport]] = {}
        self._social_cache: dict[tuple[str, str], tuple[float, socials_mod.SocialReport]] = {}

    # ------------------------------------------------------------------ whales
    def poll_whales(self) -> list[WhaleTrade]:
        min_ts = int(time.time() - self.cfg.whales.lookback_minutes * 60)
        new: list[WhaleTrade] = []
        for whale in self.cfg.whales.wallets:
            key = f"{whale.chain}:{whale.address}"
            try:
                if whale.chain == "solana":
                    trades, cursor = self.sol.poll(whale, self.store.get_cursor(key), min_ts)
                else:
                    since = int(self.store.get_cursor(key) or 0)
                    trades, cursor = self.evm.poll(whale, since, min_ts)
                self.store.set_cursor(key, cursor)
                new += self.store.add_whale_trades(trades)
            except Exception as exc:
                log.warning("whale poll failed for %s: %s", whale.name, exc)
        for t in new:
            log.info("whale %s %s %s on %s (%.4g tokens)", t.wallet_label, t.side, t.token, t.chain, t.amount)
        return new

    def _exit_alerts(self, sells: list[WhaleTrade]) -> None:
        """Warn when a tracked whale sells a token we already signalled."""
        for t in sells:
            last = self.store.last_signal(t.chain, t.token)
            if last is None:
                continue
            self.alerter.send(
                f"<b>🚪 WHALE EXIT — ${last['symbol']}</b>\n{t.wallet_label} is selling "
                f"{t.amount:,.0f} tokens.\nConsider taking profit / tightening your stop.\n"
                f'<a href="{last["pair_url"]}">DexScreener</a>')

    # ------------------------------------------------------------------ enrichment
    def _cached(self, cache: dict, key, fn):
        hit = cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
        value = fn()
        cache[key] = (time.time(), value)
        return value

    def safety_for(self, p: Pair) -> safety_mod.SafetyReport:
        return self._cached(self._safety_cache, (p.chain, p.token_address),
                            lambda: safety_mod.check(self.http, p.chain, p.token_address, self.cfg.safety))

    def social_for(self, p: Pair) -> socials_mod.SocialReport:
        return self._cached(self._social_cache, (p.chain, p.token_address),
                            lambda: socials_mod.check(self.http, p, self.cfg.secrets.telegram_bot_token,
                                                      self.cfg.socials.check_telegram_members,
                                                      self.cfg.socials.check_website))

    # ------------------------------------------------------------------ evaluation
    def evaluate(self, p: Pair, whale_buys: list[WhaleTrade], force: bool = False) -> tuple[Signal | None, str]:
        """Return (signal, reason). Signal is None when rejected."""
        reject = hard_filter(p, self.cfg.filters)
        # A whale buying an older token is still worth a look, so only the age filter is relaxed.
        if reject and not (whale_buys and reject.startswith("too old")) and not force:
            return None, reject

        # Cheap pre-check before hitting the rate-limited safety/social APIs.
        mom, _, _ = momentum_score(p)
        best_case = mom + 20 + 10 + early_score(p) + (30 if whale_buys else 0)
        if best_case < self.cfg.scoring.alert_threshold and not whale_buys and not force:
            return None, f"momentum too weak ({mom:.0f}/35)"

        sreport = self.safety_for(p)
        if not sreport.ok and not force:
            return None, "unsafe: " + ", ".join(sreport.flags[:3])
        social = self.social_for(p)
        return build_signal(p, sreport, social, whale_buys), "ok"

    def scan(self) -> list[Signal]:
        new_trades = self.poll_whales()
        new_whale_tokens = {(t.chain, t.token) for t in new_trades if t.side == "buy"}
        self._exit_alerts([t for t in new_trades if t.side == "sell"])

        candidates = set(self.dex.discover(self.cfg.chains)) | new_whale_tokens
        by_chain: dict[str, list[str]] = defaultdict(list)
        for chain, addr in candidates:
            by_chain[chain].append(addr)

        since = int(time.time() - self.cfg.whales.lookback_minutes * 60)
        fired: list[Signal] = []
        rejected = 0
        for chain, addrs in by_chain.items():
            try:
                pairs = self.dex.pairs_for_tokens(chain, addrs)
            except Exception as exc:
                log.warning("pair fetch failed for %s: %s", chain, exc)
                continue
            for addr, pair in pairs.items():
                buys = self.store.recent_whale_buys(chain, addr, since)
                try:
                    sig, why = self.evaluate(pair, buys)
                except Exception as exc:
                    log.debug("evaluate %s failed: %s", pair.symbol, exc)
                    continue
                if sig is None:
                    rejected += 1
                    log.debug("skip %s %s: %s", chain, pair.symbol, why)
                    continue
                is_new_whale = (chain, addr) in new_whale_tokens
                passes = sig.score >= self.cfg.scoring.alert_threshold or (
                    is_new_whale and self.cfg.scoring.whale_alert_always)
                if passes and self.store.should_alert(chain, addr, sig.score, is_new_whale):
                    self.store.add_signal(sig)
                    self.alerter.signal(sig)
                    fired.append(sig)
                else:
                    log.debug("below threshold %s %.0f", pair.symbol, sig.score)
        log.info("scanned %d tokens, %d rejected by filters, %d alerts", len(candidates), rejected, len(fired))
        return fired

    # ------------------------------------------------------------------ outcome tracking
    def track_outcomes(self) -> None:
        due = self.store.due_outcomes(self.cfg.tracker.checkpoints_minutes)
        if not due:
            return
        by_chain: dict[str, set[str]] = defaultdict(set)
        for row, _ in due:
            by_chain[row["chain"]].add(row["token"])
        prices: dict[tuple[str, str], float] = {}
        for chain, tokens in by_chain.items():
            try:
                pairs = self.dex.pairs_for_tokens(chain, list(tokens))
            except Exception as exc:
                log.warning("outcome price fetch failed: %s", exc)
                continue
            for t in tokens:
                # A token that disappeared from DexScreener after a successful fetch is almost always rugged.
                prices[(chain, t)] = pairs[t].price_usd if t in pairs else 0.0
        for row, minutes in due:
            key = (row["chain"], row["token"])
            if key in prices:
                self.store.add_outcome(row["id"], minutes, prices[key], row["price_usd"])

    # ------------------------------------------------------------------ loop
    def run_forever(self) -> None:
        log.info("whalebot started: chains=%s whales=%d telegram=%s threshold=%s",
                 ",".join(self.cfg.chains), len(self.cfg.whales.wallets), self.alerter.telegram_enabled,
                 self.cfg.scoring.alert_threshold)
        while True:
            started = time.time()
            try:
                self.scan()
                self.track_outcomes()
            except KeyboardInterrupt:
                raise
            except Exception:
                log.exception("scan cycle failed")
            time.sleep(max(5.0, self.cfg.scan_interval_seconds - (time.time() - started)))


def describe(sig: Signal | None, why: str, p: Pair) -> str:
    head = f"{p.symbol} ({p.chain}) MC {money(p.market_cap)} Liq {money(p.liquidity_usd)} age {p.age_hours:.1f}h"
    if sig is None:
        return f"{head}\nREJECTED: {why}"
    return (f"{head}\nSCORE {sig.score:.0f}/100  {sig.parts}\n"
            + "\n".join(f"  + {r}" for r in sig.reasons) + "\n"
            + "\n".join(f"  ! {w}" for w in sig.warnings))
