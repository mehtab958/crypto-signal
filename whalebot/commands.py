"""Telegram command interface: ask the bot for signals on demand.

Only messages from TELEGRAM_CHAT_ID are answered, so strangers who find your bot can't use it.
"""

from __future__ import annotations

import html
import logging
import threading
import time

from .alerts import format_signal, money
from .bot import Bot
from .dexscreener import best_pair_any_chain
from .scoring import hard_filter

log = logging.getLogger(__name__)

HELP = """<b>whalebot commands</b>
/top — best signals right now (add a number: /top 5)
/check &lt;address&gt; — score any token (chain auto-detected)
/check &lt;chain&gt; &lt;address&gt; — e.g. /check base 0x…
/whales — latest trades from your tracked wallets
/report — how past signals performed
/status — current settings
/threshold &lt;n&gt; — change alert score threshold (0-100)
/pause · /resume — stop / restart automatic alerts
/help — this message"""


def top(bot: Bot, n: int = 3, min_score: float = 40) -> str | list[str]:
    signals = bot.score_candidates(min_score=min_score)
    signals = [s for s in signals if s.score >= min_score][:n]
    if not signals:
        return ("😴 Nothing worth flagging right now — no new token passes the filters and safety checks "
                f"with a score ≥ {min_score:.0f}. Try again in a few minutes.")
    return [format_signal(s) for s in signals]


def check(bot: Bot, args: list[str]) -> str:
    if not args:
        return "Usage: /check &lt;address&gt; or /check &lt;chain&gt; &lt;address&gt;"
    if len(args) >= 2:
        chain, address = args[0].lower(), args[1]
        pair = next(iter(bot.dex.pairs_for_tokens(chain, [address]).values()), None)
    else:
        address = args[0]
        pair = best_pair_any_chain(bot.dex, address)
    if pair is None:
        return "❌ Token not found on DexScreener."
    since = int(time.time() - bot.cfg.whales.lookback_minutes * 60)
    sig, _ = bot.evaluate(pair, bot.store.recent_whale_buys(pair.chain, pair.token_address, since), force=True)
    safety = bot.safety_for(pair)
    notes = []
    if not safety.ok:
        notes.append("🚫 <b>FAILS SAFETY CHECK — do not buy</b>")
    reject = hard_filter(pair, bot.cfg.filters)
    if reject:
        notes.append(f"ℹ️ Would be skipped by live filters: {html.escape(reject)}")
    return "\n".join(notes + [format_signal(sig)]) if sig else "Could not score this token."


def whales(bot: Bot) -> str:
    if not bot.cfg.whales.wallets:
        return ("No whale wallets configured. Add them under <code>whales:</code> in config.yaml "
                "(see README → Whale wallets).")
    bot.poll_whales()
    rows = bot.store.recent_whale_trades(15)
    if not rows:
        return f"Tracking {len(bot.cfg.whales.wallets)} wallet(s). No trades seen yet."
    lines = [f"<b>Latest whale trades</b> ({len(bot.cfg.whales.wallets)} wallets)"]
    for r in rows:
        ago = (time.time() - r["timestamp"]) / 60
        icon = "🟢" if r["side"] == "buy" else "🔴"
        spent = f" for {r['quote_amount']:.2f} SOL" if r["quote_amount"] else ""
        lines.append(f"{icon} {html.escape(r['wallet_label'] or '')} {r['side']}{spent} · {r['chain']} · "
                     f"{ago:.0f}m ago\n<code>{html.escape(r['token'])}</code>")
    return "\n".join(lines)


def report(bot: Bot) -> str:
    perf = bot.store.performance()
    if not perf:
        return "No results yet — signals are re-checked 15m / 1h / 4h / 24h after they fire."
    lines = ["<b>Signal performance</b>", "<pre>after    n  avg x  ≥+20%  ≥2x  ≤-50%"]
    for r in perf:
        n = r["n"] or 1
        lines.append(f"{r['minutes']:>4}m {r['n']:>4} {r['avg_mult']:>6.2f} {100 * r['up20'] / n:>5.0f}% "
                     f"{100 * r['x2'] / n:>4.0f}% {100 * r['down50'] / n:>5.0f}%")
    lines.append("</pre>")
    return "\n".join(lines)


def status(bot: Bot) -> str:
    c = bot.cfg
    f = c.filters
    return (f"<b>Status</b>\nalerts: {'⏸ paused' if bot.alerts_paused else '▶️ on'}\n"
            f"chains: {', '.join(c.chains)}\nthreshold: {c.scoring.alert_threshold:.0f}/100\n"
            f"whale wallets: {len(c.whales.wallets)}\n"
            f"filters: age ≤ {f.max_age_hours:g}h · liq {money(f.min_liquidity_usd)}–{money(f.max_liquidity_usd)} · "
            f"mcap {money(f.min_market_cap_usd)}–{money(f.max_market_cap_usd)}\n"
            f"scan every {c.scan_interval_seconds:.0f}s")


def handle(bot: Bot, text: str) -> str | list[str]:
    parts = text.strip().split()
    if not parts:
        return HELP
    cmd = parts[0].split("@")[0].lower()  # "/top@MyBot" in groups
    args = parts[1:]
    if cmd in ("/start", "/help"):
        return HELP
    if cmd in ("/top", "/signal", "/signals"):
        n = int(args[0]) if args and args[0].isdigit() else 3
        return top(bot, max(1, min(n, 10)))
    if cmd == "/check":
        return check(bot, args)
    if cmd == "/whales":
        return whales(bot)
    if cmd == "/report":
        return report(bot)
    if cmd == "/status":
        return status(bot)
    if cmd == "/threshold":
        if not args:
            return f"Current threshold: {bot.cfg.scoring.alert_threshold:.0f}"
        try:
            bot.cfg.scoring.alert_threshold = max(0.0, min(100.0, float(args[0])))
        except ValueError:
            return "Usage: /threshold 65"
        return f"✅ Alert threshold set to {bot.cfg.scoring.alert_threshold:.0f} (until restart)"
    if cmd == "/pause":
        bot.alerts_paused = True
        return "⏸ Automatic alerts paused. Commands still work. /resume to restart."
    if cmd == "/resume":
        bot.alerts_paused = False
        return "▶️ Automatic alerts resumed."
    # Pasting a bare address is a shortcut for /check.
    token = parts[0]
    if len(parts) == 1 and ((token.startswith("0x") and len(token) == 42) or 32 <= len(token) <= 44):
        return check(bot, parts)
    return "Unknown command.\n\n" + HELP


SLOW = {"/top", "/signal", "/signals", "/check", "/whales"}


class CommandListener:
    def __init__(self, bot: Bot):
        self.bot = bot
        self.token = bot.cfg.secrets.telegram_bot_token
        self.chat_id = str(bot.cfg.secrets.telegram_chat_id)
        self.offset = 0

    def reply(self, chat_id, text: str) -> None:
        self.bot.alerter.send_to(chat_id, text)

    def poll_once(self) -> None:
        data = self.bot.http.get(f"https://api.telegram.org/bot{self.token}/getUpdates",
                                 params={"offset": self.offset, "timeout": 25}, timeout=40) or {}
        for update in data.get("result") or []:
            self.offset = update["update_id"] + 1
            msg = update.get("message") or update.get("channel_post") or {}
            text = msg.get("text") or ""
            chat_id = str((msg.get("chat") or {}).get("id", ""))
            if not text or not chat_id:
                continue
            if chat_id != self.chat_id:
                log.warning("ignoring message from unauthorised chat %s", chat_id)
                continue
            log.info("command: %s", text)
            if text.split()[0].split("@")[0].lower() in SLOW:
                self.reply(chat_id, "⏳ Scanning… this can take up to a minute.")
            try:
                with self.bot.lock:
                    result = handle(self.bot, text)
            except Exception as exc:
                log.exception("command failed")
                result = f"⚠️ Error: {html.escape(str(exc))}"
            for chunk in result if isinstance(result, list) else [result]:
                self.reply(chat_id, chunk)

    def register_menu(self) -> None:
        """Show the commands in Telegram's "/" menu."""
        commands = [("top", "Best signals right now"), ("check", "Score a token: /check <address>"),
                    ("whales", "Latest whale trades"), ("report", "How past signals performed"),
                    ("status", "Current settings"), ("threshold", "Change alert threshold"),
                    ("pause", "Pause automatic alerts"), ("resume", "Resume automatic alerts"),
                    ("help", "Show help")]
        try:
            self.bot.http.post(f"https://api.telegram.org/bot{self.token}/setMyCommands", json={
                "commands": [{"command": c, "description": d} for c, d in commands]})
        except Exception as exc:
            log.debug("setMyCommands failed: %s", exc)

    def run_forever(self) -> None:
        self.register_menu()
        log.info("listening for Telegram commands")
        while True:
            try:
                self.poll_once()
            except Exception as exc:
                log.warning("telegram polling error: %s", exc)
                time.sleep(5)

    def start_thread(self) -> threading.Thread:
        t = threading.Thread(target=self.run_forever, name="telegram-commands", daemon=True)
        t.start()
        return t
