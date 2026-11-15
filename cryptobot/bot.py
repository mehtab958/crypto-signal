#!/usr/bin/env python3
"""Binance PAPER-trading bot for spot and futures. No real money, no API keys.

Every run it:
  1. reads all Binance USDT spot markets from the public market-data API,
  2. keeps the liquid ones and studies the most active with 15-minute candles,
  3. manages open paper positions candle by candle (stop, target, trailing, time),
  4. opens new paper trades when a strategy fires,
  5. writes everything to data.json for the results page.

"Futures" trades are simulated on the same prices with leverage and can go short.
Usage: bot.py <output_dir>
"""
import json
import os
import sys
import time
import urllib.request

BASES = ["https://data-api.binance.vision", "https://api.binance.com", "https://api-gcp.binance.com", "https://api1.binance.com"]
_base = [None]

CFG = {
    "min_quote_volume": 5_000_000,   # 24h USD volume a coin needs to be considered
    "study_top": 45,                 # coins studied in detail each run
    "interval": "15m",
    # spot paper account
    "spot_start": 500.0, "spot_stake": 50.0, "spot_max_open": 5,
    "spot_tp": 0.09, "spot_sl": 0.03, "spot_trail_arm": 0.04, "spot_trail_drop": 0.025, "spot_max_hold_h": 24,
    "spot_fee": 0.001,
    # futures paper account: 5x leverage, so a 9% price move = 45% on the margin
    "fut_start": 500.0, "fut_margin": 25.0, "fut_leverage": 5, "fut_max_open": 5,
    "fut_tp": 0.09, "fut_sl": 0.03, "fut_trail_arm": 0.045, "fut_trail_drop": 0.025, "fut_max_hold_h": 12,
    "fut_fee": 0.0005,
    "slippage": 0.0005,
    "cooldown_h": 6,                 # no new trade in the same coin and account for this long after a close
    "score_trades": 15, "pause_h": 24,   # a strategy whose last 15 trades lose money is paused for 24h
}

SKIP_BASES = {"USDC", "FDUSD", "TUSD", "USDP", "DAI", "BUSD", "EUR", "EURI", "AEUR", "USD1", "XUSD", "BFUSD", "USDE", "PAXG", "WBTC", "WBETH", "BNSOL"}
STRATEGIES = ["breakout", "pullback", "oversold bounce", "breakdown", "overbought fade"]


def get(path):
    """GET JSON from Binance public market data, trying mirrors. Returns None on failure."""
    bases = [_base[0]] if _base[0] else BASES
    for base in bases:
        for attempt in range(2):
            try:
                req = urllib.request.Request(base + path, headers={"User-Agent": "cryptobot-paper/1.0"})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                _base[0] = base
                return data
            except Exception as exc:
                print("request failed (%s%s): %s" % (base, path[:50], exc))
                time.sleep(1 + attempt)
    return None


def klines(symbol, limit=130):
    data = get("/api/v3/klines?symbol=%s&interval=%s&limit=%d" % (symbol, CFG["interval"], limit))
    if not isinstance(data, list) or len(data) < 60:
        return None
    try:
        return [{"t": int(k[0]), "o": float(k[1]), "h": float(k[2]), "l": float(k[3]), "c": float(k[4]), "v": float(k[5])} for k in data]
    except (TypeError, ValueError, IndexError):
        return None


# ---------- indicators ----------
def ema(values, n):
    out, k, e = [], 2.0 / (n + 1), values[0]
    for i, v in enumerate(values):
        e = v if i == 0 else v * k + e * (1 - k)
        out.append(e)
    return out


def rsi(values, n=14):
    out, gain, loss = [50.0], 0.0, 0.0
    for i in range(1, len(values)):
        d = values[i] - values[i - 1]
        up, dn = max(d, 0.0), max(-d, 0.0)
        if i <= n:
            gain += up / n
            loss += dn / n
        else:
            gain = (gain * (n - 1) + up) / n
            loss = (loss * (n - 1) + dn) / n
        out.append(50.0 if i < n else (100.0 if loss == 0 else 100 - 100 / (1 + gain / loss)))
    return out


def bands(values, i, n=20, mult=2.0):
    window = values[i - n + 1:i + 1]
    mean = sum(window) / n
    sd = (sum((v - mean) ** 2 for v in window) / n) ** 0.5
    return mean - mult * sd, mean + mult * sd


def signal(c):
    """Reads the last CLOSED candle. Returns (direction, strategy) or (0, '')."""
    i = len(c) - 2
    if i < 55:
        return 0, ""
    closes = [x["c"] for x in c[:i + 1]]
    e20, e50, r = ema(closes, 20), ema(closes, 50), rsi(closes)
    k, prev = c[i], c[i - 1]
    hi20 = max(x["h"] for x in c[i - 20:i])
    lo20 = min(x["l"] for x in c[i - 20:i])
    avg_vol = sum(x["v"] for x in c[i - 20:i]) / 20
    up_trend = e20[i] > e50[i] and k["c"] > e50[i]
    down_trend = e20[i] < e50[i] and k["c"] < e50[i]
    lo_band, hi_band = bands(closes, i)
    lo_prev, hi_prev = bands(closes, i - 1)

    if up_trend and k["c"] > hi20 and k["v"] >= 2 * avg_vol and 55 <= r[i] <= 78:
        return 1, "breakout"
    if up_trend and min(k["l"], prev["l"]) <= e20[i] * 1.002 and k["c"] > e20[i] and k["c"] > k["o"] and min(r[i - 3:i]) < 48 and r[i] > r[i - 1]:
        return 1, "pullback"
    if r[i - 1] < 25 and prev["c"] < lo_prev and k["c"] > lo_band and k["c"] > k["o"]:
        return 1, "oversold bounce"
    if down_trend and k["c"] < lo20 and k["v"] >= 2 * avg_vol and 22 <= r[i] <= 45:
        return -1, "breakdown"
    if r[i - 1] > 80 and prev["c"] > hi_prev and k["c"] < hi_band and k["c"] < k["o"]:
        return -1, "overbought fade"
    return 0, ""


# ---------- paper accounts ----------
def new_state():
    return {"spot": {"cash": CFG["spot_start"], "positions": []}, "fut": {"cash": CFG["fut_start"], "positions": []},
            "closed": [], "equity": [], "cooldown": {}, "runs": 0}


def load_state(path):
    try:
        with open(path) as fh:
            state = json.load(fh)
        if isinstance(state, dict) and "spot" in state and "fut" in state:
            return state
    except (OSError, ValueError):
        pass
    return new_state()


def params(account):
    p = "spot_" if account == "spot" else "fut_"
    return {k[len(p):]: v for k, v in CFG.items() if k.startswith(p)}


def value(pos, price):
    """Current worth of a position's stake at this price (before exit costs)."""
    move = (price / pos["entry"] - 1) * pos["dir"]
    return pos["stake"] * (1 + move * pos["lev"])


def close(state, account, pos, price, why, now):
    p = params(account)
    price = price * (1 - CFG["slippage"] * pos["dir"])
    worth = value(pos, price) - pos["stake"] * pos["lev"] * p["fee"]
    worth = max(worth, 0.0)
    state[account]["cash"] += worth
    pnl = worth - pos["stake"] - pos["open_fee"]
    state["closed"].insert(0, {
        "account": account, "symbol": pos["symbol"], "dir": pos["dir"], "strategy": pos["strategy"],
        "entry_time": pos["time"], "exit_time": int(now), "entry": pos["entry"], "exit": price,
        "stake": pos["stake"], "pnl": round(pnl, 2), "pnl_pct": round(pnl / pos["stake"] * 100, 1), "why": why,
    })
    state["cooldown"][account + ":" + pos["symbol"]] = int(now)
    print("CLOSE %s %s %s: %s, pnl %.2f" % (account, pos["symbol"], "long" if pos["dir"] > 0 else "short", why, pnl))


def manage(state, account, candles, now):
    """Walk each open position through the candles since it was last checked."""
    p = params(account)
    keep = []
    for pos in state[account]["positions"]:
        c = candles.get(pos["symbol"])
        if not c:
            pos["misses"] = pos.get("misses", 0) + 1
            keep.append(pos)
            continue
        done = False
        for k in c:
            if k["t"] < pos["checked"]:
                continue
            d = pos["dir"]
            worst, best = (k["l"], k["h"]) if d > 0 else (k["h"], k["l"])
            stop = pos["entry"] * (1 - p["sl"] * d)
            target = pos["entry"] * (1 + p["tp"] * d)
            trail = None
            if (pos["peak"] / pos["entry"] - 1) * d >= p["trail_arm"]:
                trail = pos["peak"] * (1 - p["trail_drop"] * d)
            # the worst price of the candle is assumed to come first (conservative)
            if (worst - stop) * d <= 0:
                close(state, account, pos, stop, "stop loss", now); done = True; break
            if trail is not None and (worst - trail) * d <= 0:
                close(state, account, pos, trail, "trailing stop", now); done = True; break
            if (best - target) * d >= 0:
                close(state, account, pos, target, "take profit", now); done = True; break
            if (best - pos["peak"]) * d > 0:
                pos["peak"] = best
            pos["checked"] = k["t"]
            pos["last"] = k["c"]
        if done:
            continue
        if now - pos["time"] >= p["max_hold_h"] * 3600:
            close(state, account, pos, pos["last"], "time limit", now)
            continue
        keep.append(pos)
    state[account]["positions"] = keep


def paused_strategies(state, now):
    paused = []
    for name in STRATEGIES:
        mine = [t for t in state["closed"] if t["strategy"] == name][:CFG["score_trades"]]
        if len(mine) >= 8 and sum(t["pnl"] for t in mine) < 0 and now - mine[0]["exit_time"] < CFG["pause_h"] * 3600:
            paused.append(name)
    return paused


def open_position(state, account, symbol, direction, strategy, price, candle_time, now):
    p = params(account)
    stake = p["stake"] if account == "spot" else p["margin"]
    lev = 1 if account == "spot" else p["leverage"]
    fee = stake * lev * p["fee"]
    if state[account]["cash"] < stake + fee or len(state[account]["positions"]) >= p["max_open"]:
        return False
    entry = price * (1 + CFG["slippage"] * direction)
    state[account]["cash"] -= stake + fee
    state[account]["positions"].append({
        "symbol": symbol, "dir": direction, "strategy": strategy, "entry": entry, "last": price, "peak": entry,
        "stake": stake, "lev": lev, "open_fee": fee, "time": int(now), "checked": candle_time, "misses": 0,
    })
    print("OPEN %s %s %s (%s) at %g" % (account, symbol, "long" if direction > 0 else "short", strategy, entry))
    return True


def universe():
    data = get("/api/v3/ticker/24hr")
    if not isinstance(data, list):
        return None
    coins = []
    for t in data:
        try:
            symbol = t["symbol"]
            if not symbol.endswith("USDT"):
                continue
            base = symbol[:-4]
            if base in SKIP_BASES or base.endswith(("UP", "DOWN", "BULL", "BEAR")):
                continue
            volume, change, price = float(t["quoteVolume"]), float(t["priceChangePercent"]), float(t["lastPrice"])
            if volume < CFG["min_quote_volume"] or price <= 0:
                continue
            coins.append({"symbol": symbol, "volume": volume, "change": change})
        except (KeyError, TypeError, ValueError):
            continue
    return coins


def run(out_dir, now=None):
    now = now or time.time()
    path = os.path.join(out_dir, "data.json")
    state = load_state(path)
    state["runs"] = state.get("runs", 0) + 1

    coins = universe()
    api_ok = coins is not None
    coins = coins or []
    # most active first: big movers with real volume
    coins.sort(key=lambda x: -(abs(x["change"]) * (x["volume"] ** 0.5)))
    study = [x["symbol"] for x in coins[:CFG["study_top"]]]
    held = [p["symbol"] for a in ("spot", "fut") for p in state[a]["positions"]]
    candles = {}
    for symbol in dict.fromkeys(held + ["BTCUSDT"] + study):
        c = klines(symbol, 260 if symbol == "BTCUSDT" else 130)
        if c:
            candles[symbol] = c

    for account in ("spot", "fut"):
        manage(state, account, candles, now)

    # market mood from Bitcoin: longs only when BTC is above its 200-candle average, shorts only below
    mood = 0
    btc = candles.get("BTCUSDT")
    if btc and len(btc) >= 210:
        closes = [x["c"] for x in btc[:-1]]
        mood = 1 if closes[-1] > ema(closes, 200)[-1] else -1

    state["cooldown"] = {k: t for k, t in state["cooldown"].items() if now - t < CFG["cooldown_h"] * 3600}
    paused = paused_strategies(state, now)
    found = []
    for symbol in study:
        c = candles.get(symbol)
        if not c:
            continue
        direction, strategy = signal(c)
        if direction == 0:
            continue
        found.append([symbol, direction, strategy])
        if strategy in paused:
            continue
        if direction != mood and strategy in ("breakout", "pullback", "breakdown"):
            continue        # trend trades must agree with Bitcoin's direction
        price, candle_time = c[-1]["c"], c[-1]["t"]
        for account in (("spot", "fut") if direction > 0 else ("fut",)):
            if any(p["symbol"] == symbol for p in state[account]["positions"]):
                continue
            if account + ":" + symbol in state["cooldown"]:
                continue
            open_position(state, account, symbol, direction, strategy, price, candle_time, now)

    # bookkeeping for the page
    summary = {"updated": int(now), "api_ok": api_ok, "coins": len(coins), "studied": len(study), "signals": found[:12],
               "mood": mood, "paused": paused, "source": _base[0]}
    total = 0.0
    for account, start in (("spot", CFG["spot_start"]), ("fut", CFG["fut_start"])):
        acc = state[account]
        equity = acc["cash"] + sum(max(value(p, p["last"]), 0.0) for p in acc["positions"])
        trades = [t for t in state["closed"] if t["account"] == account]
        wins = [t for t in trades if t["pnl"] > 0]
        summary[account] = {"start": start, "equity": round(equity, 2), "cash": round(acc["cash"], 2), "trades": len(trades),
                            "win_rate": round(100.0 * len(wins) / len(trades), 1) if trades else None}
        total += equity
    table = []
    for name in STRATEGIES:
        mine = [t for t in state["closed"] if t["strategy"] == name]
        if mine:
            table.append([name, len(mine), round(100.0 * len([t for t in mine if t["pnl"] > 0]) / len(mine)), round(sum(t["pnl"] for t in mine), 2)])
    summary["strategies"] = table
    state["summary"] = summary
    state["equity"].append([int(now), round(total, 2)])
    state["equity"] = state["equity"][-1500:]
    state["closed"] = state["closed"][:400]
    state["config"] = CFG

    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(state, fh, indent=1)
    print("coins %d, studied %d, signals %d, mood %d, spot %.2f, futures %.2f, source %s" % (
        len(coins), len(candles), len(found), mood, summary["spot"]["equity"], summary["fut"]["equity"], _base[0]))
    return state


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "out")
