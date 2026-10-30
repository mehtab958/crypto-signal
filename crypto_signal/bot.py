"""24/7 trading bot.

    python -m crypto_signal.bot scan                       # current signals for all symbols
    python -m crypto_signal.bot run                        # trade forever (paper by default)
    python -m crypto_signal.bot run --once                 # single iteration (cron / testing)

Every iteration (after each 4h candle closes) the bot, for each symbol:
  1. fetches closed 4h and 1d candles,
  2. computes the portfolio's target position (0..1 of that symbol's capital slice),
  3. rebalances with a market order if the target moved more than `rebalance_threshold`.

Risk controls: per-symbol capital slices, minimum order size, a max-drawdown kill switch that
flattens everything and halts, and a persisted state file so restarts are safe.
"""
import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import portfolio as pf
from .data import fetch_ohlcv

log = logging.getLogger("bot")

DEFAULTS = {
    "exchange": "binance",
    "sandbox": False,
    "mode": "paper",  # paper | live
    "symbols": ["BTC/USDT"],
    "portfolio": "config/portfolio.json",
    "paper_capital": 10_000.0,
    "fee": 0.001,
    "rebalance_threshold": 0.05,
    "min_order_value": 10.0,
    "max_drawdown": 0.40,
    "poll_seconds": 60,
    "candle_delay_seconds": 30,
    "state_file": "state/bot_state.json",
    "candles": {"4h": 1000, "1d": 400},
}


def load_config(path: str | None) -> dict:
    cfg = dict(DEFAULTS)
    if path and Path(path).exists():
        cfg.update(yaml.safe_load(Path(path).read_text()) or {})
    return cfg


def make_exchange(cfg):
    import ccxt

    params = {"enableRateLimit": True}
    if cfg["mode"] == "live":
        params["apiKey"] = os.environ["EXCHANGE_API_KEY"]
        params["secret"] = os.environ["EXCHANGE_API_SECRET"]
        if os.environ.get("EXCHANGE_API_PASSWORD"):
            params["password"] = os.environ["EXCHANGE_API_PASSWORD"]
    ex = getattr(ccxt, cfg["exchange"])(params)
    if cfg.get("sandbox"):
        ex.set_sandbox_mode(True)
    ex.load_markets()
    return ex


class PaperBroker:
    """Simulated account: one cash slice per symbol, filled at the last price with fees."""

    def __init__(self, cfg, state):
        self.fee = cfg["fee"]
        if "paper" not in state:
            slice_ = cfg["paper_capital"] / len(cfg["symbols"])
            state["paper"] = {s: {"cash": slice_, "qty": 0.0} for s in cfg["symbols"]}
        self.acct = state["paper"]

    def equity(self, symbol, price):
        a = self.acct[symbol]
        return a["cash"] + a["qty"] * price

    def holding(self, symbol):
        return self.acct[symbol]["qty"]

    def order(self, symbol, side, qty, price):
        a = self.acct[symbol]
        if side == "buy":
            qty = min(qty, a["cash"] / (price * (1 + self.fee)))
            a["cash"] -= qty * price * (1 + self.fee)
            a["qty"] += qty
        else:
            qty = min(qty, a["qty"])
            a["cash"] += qty * price * (1 - self.fee)
            a["qty"] -= qty
        return {"side": side, "qty": qty, "price": price}


class LiveBroker:
    """Real orders through ccxt. Capital is split equally across symbols: each symbol's slice
    is (free quote + value of all bot symbols' base holdings) / number of symbols."""

    def __init__(self, cfg, exchange):
        self.ex = exchange
        self.symbols = cfg["symbols"]
        self._bal = None

    def _balance(self):
        if self._bal is None:
            self._bal = self.ex.fetch_balance()
        return self._bal

    def _total(self, cur):
        return float(self._balance().get(cur, {}).get("total") or 0.0)

    def holding(self, symbol):
        return self._total(self.ex.market(symbol)["base"])

    def equity(self, symbol, price, prices=None):
        quote = self.ex.market(symbol)["quote"]
        prices = prices or {symbol: price}
        held = sum(self.holding(s) * prices.get(s, price) for s in self.symbols
                   if self.ex.market(s)["quote"] == quote)
        return (self._total(quote) + held) / len(self.symbols)

    def order(self, symbol, side, qty, price):
        amount = float(self.ex.amount_to_precision(symbol, qty))
        if amount <= 0:
            return None
        o = self.ex.create_order(symbol, "market", side, amount)
        self._bal = None
        return {"side": side, "qty": amount, "price": o.get("average") or price, "id": o.get("id")}


class Bot:
    def __init__(self, cfg, exchange=None):
        self.cfg = cfg
        self.ex = exchange or make_exchange(cfg)
        _, self.members = pf.load(cfg["portfolio"])
        self.timeframes = sorted({m.timeframe for m in self.members} | {"4h"})
        self.state_path = Path(cfg["state_file"])
        self.state = json.loads(self.state_path.read_text()) if self.state_path.exists() else {}
        self.state.setdefault("peak_equity", 0.0)
        self.state.setdefault("halted", False)
        self.state.setdefault("last_bar", None)
        self.broker = (PaperBroker(cfg, self.state) if cfg["mode"] == "paper"
                       else LiveBroker(cfg, self.ex))

    def save(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, indent=2, default=str))
        tmp.replace(self.state_path)

    def signal(self, symbol) -> dict:
        frames = {tf: fetch_ohlcv(self.ex, symbol, tf, self.cfg["candles"].get(tf, 500))
                  for tf in self.timeframes}
        per = pf.member_positions(self.members, frames, "4h").iloc[-1]
        target = float(per.mean())
        return {"symbol": symbol, "bar": frames["4h"].index[-1], "price":
                float(frames["4h"]["close"].iloc[-1]), "target": target, "members": per.to_dict()}

    def scan(self):
        out = []
        for s in self.cfg["symbols"]:
            try:
                out.append(self.signal(s))
            except Exception as e:  # keep scanning other symbols
                log.error("scan %s failed: %s", s, e)
        return out

    def step(self):
        """One iteration: compute signals, enforce the kill switch, rebalance."""
        if isinstance(self.broker, LiveBroker):
            self.broker._bal = None
        sigs = self.scan()
        if not sigs:
            return []
        prices = {s["symbol"]: s["price"] for s in sigs}
        if isinstance(self.broker, LiveBroker):
            equities = {s: self.broker.equity(s, p, prices) for s, p in prices.items()}
        else:
            equities = {s: self.broker.equity(s, p) for s, p in prices.items()}
        total = sum(equities.values())
        self.state["peak_equity"] = max(self.state["peak_equity"], total)
        dd = 1 - total / self.state["peak_equity"] if self.state["peak_equity"] else 0.0
        if dd >= self.cfg["max_drawdown"] and not self.state["halted"]:
            log.critical("KILL SWITCH: drawdown %.1f%% >= %.1f%%. Flattening and halting.",
                         dd * 100, self.cfg["max_drawdown"] * 100)
            self.state["halted"] = True
        fills = []
        for sig in sigs:
            sym, price = sig["symbol"], sig["price"]
            target = 0.0 if self.state["halted"] else sig["target"]
            eq = equities[sym]
            cur_val = self.broker.holding(sym) * price
            cur = cur_val / eq if eq > 0 else 0.0
            diff = target - cur
            log.info("%s price=%.2f target=%.2f current=%.2f members=%s", sym, price, target, cur,
                     {k: round(v, 2) for k, v in sig["members"].items()})
            moving_to_flat = target == 0 and cur_val > self.cfg["min_order_value"]
            if abs(diff) < self.cfg["rebalance_threshold"] and not moving_to_flat:
                continue
            value = abs(diff) * eq
            if value < self.cfg["min_order_value"]:
                continue
            side = "buy" if diff > 0 else "sell"
            qty = self.broker.holding(sym) if target == 0 else value / price
            try:
                fill = self.broker.order(sym, side, qty, price)
            except Exception as e:
                log.error("order %s %s failed: %s", side, sym, e)
                continue
            if fill:
                fill.update(symbol=sym, time=datetime.now(timezone.utc).isoformat())
                log.info("FILL %s", fill)
                self.state.setdefault("fills", []).append(fill)
                fills.append(fill)
        self.state["last_bar"] = str(sigs[0]["bar"])
        self.state["equity"] = total
        self.state["drawdown"] = dd
        self.save()
        log.info("equity=%.2f peak=%.2f drawdown=%.1f%% halted=%s", total,
                 self.state["peak_equity"], dd * 100, self.state["halted"])
        return fills

    def run_forever(self):
        """Wake up shortly after every 4h candle close; survive network/exchange errors."""
        period = 4 * 3600
        log.info("bot started: mode=%s exchange=%s symbols=%s members=%s", self.cfg["mode"],
                 self.cfg["exchange"], self.cfg["symbols"], [m.key for m in self.members])
        last_slot, backoff = None, 5
        while True:
            now = time.time()
            slot = int((now - self.cfg["candle_delay_seconds"]) // period)
            if slot != last_slot:
                try:
                    self.step()
                    last_slot, backoff = slot, 5
                except Exception:
                    log.exception("iteration failed, retrying in %ss", backoff)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 600)
                    continue
            time.sleep(self.cfg["poll_seconds"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["scan", "run"])
    ap.add_argument("--config", default="config/bot.yaml")
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--symbols", nargs="*", help="override symbols from config")
    a = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.StreamHandler(), logging.FileHandler("bot.log")])
    cfg = load_config(a.config)
    if a.symbols:
        cfg["symbols"] = a.symbols
    if a.command == "scan":
        cfg["mode"] = "paper"
        bot = Bot(cfg)
        for s in sorted(bot.scan(), key=lambda s: -s["target"]):
            print(f"{s['symbol']:12s} {s['price']:>12.4f}  target {s['target']:5.2f}  "
                  + "  ".join(f"{k}={v:.2f}" for k, v in s["members"].items()))
        return
    if cfg["mode"] == "live":
        log.warning("LIVE MODE: real orders will be placed on %s", cfg["exchange"])
    bot = Bot(cfg)
    if a.once:
        bot.step()
    else:
        bot.run_forever()


if __name__ == "__main__":
    main()
