#!/usr/bin/env python3
"""Memecoin PAPER-trading bot. No real money, no wallet, no keys.

Every run it:
  1. reads new / promoted tokens from DexScreener's public API,
  2. checks the open paper positions and closes those that hit an exit rule,
  3. "buys" new tokens that pass the safety and momentum rules,
  4. writes everything to data.json for the results page.

Usage: bot.py <output_dir>
"""
import json
import os
import sys
import time
import urllib.request

API = "https://api.dexscreener.com"
CHAIN = "solana"

CFG = {
    "start_cash": 200.0,     # pretend dollars
    "stake": 20.0,           # pretend dollars per trade
    "max_open": 5,
    # safety
    "min_liquidity": 20000,  # USD in the pool
    "min_age_min": 20,       # skip the first minutes (most rugs happen here)
    "max_age_h": 48,
    "max_vol_to_liq": 10,    # 1h volume far above liquidity looks like wash trading
    "min_txns_h1": 100,
    "min_sell_share": 0.15,  # if almost nobody sells, it may be a honeypot
    "fdv_min": 50000,
    "fdv_max": 20000000,
    # momentum
    "min_vol_h1": 10000,
    "min_buy_ratio": 1.1,    # buys / sells in the last hour
    "h1_change_min": 5,      # % price change, last hour
    "h1_change_max": 150,    # already vertical = too late
    # exits
    "take_profit": 0.50,
    "stop_loss": 0.25,
    "trail_arm": 0.25,       # once up 25% ...
    "trail_drop": 0.20,      # ... sell if it falls 20% from its peak
    "max_hold_h": 6,
    "slippage": 0.03,        # cost applied on every buy and sell
    "cooldown_h": 24,        # do not re-buy the same token within this time
}


def get(path):
    """GET JSON from DexScreener with a few retries. Returns None on failure."""
    for attempt in range(3):
        try:
            req = urllib.request.Request(API + path, headers={"User-Agent": "memebot-paper/1.0", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # network errors, 429, bad JSON
            print("request failed (%s): %s" % (path[:60], exc))
            time.sleep(2 * (attempt + 1))
    return None


def num(obj, *keys):
    """Nested lookup that always returns a float."""
    for key in keys:
        if not isinstance(obj, dict):
            return 0.0
        obj = obj.get(key)
    try:
        return float(obj)
    except (TypeError, ValueError):
        return 0.0


def candidate_addresses():
    found = []
    for path in ("/token-profiles/latest/v1", "/token-boosts/latest/v1", "/token-boosts/top/v1"):
        data = get(path)
        if not isinstance(data, list):
            continue
        for item in data:
            if isinstance(item, dict) and item.get("chainId") == CHAIN and item.get("tokenAddress"):
                if item["tokenAddress"] not in found:
                    found.append(item["tokenAddress"])
    return found


def best_pairs(addresses):
    """Most liquid pair for each token address. Returns {address: pair}."""
    best = {}
    for i in range(0, len(addresses), 30):
        chunk = addresses[i:i + 30]
        data = get("/tokens/v1/%s/%s" % (CHAIN, ",".join(chunk)))
        if isinstance(data, dict):
            data = data.get("pairs")
        if not isinstance(data, list):
            continue
        for pair in data:
            if not isinstance(pair, dict):
                continue
            address = (pair.get("baseToken") or {}).get("address")
            if address not in chunk:
                continue
            if address not in best or num(pair, "liquidity", "usd") > num(best[address], "liquidity", "usd"):
                best[address] = pair
    return best


def check(pair, now):
    """Returns (passes, score, reason)."""
    c = CFG
    price = num(pair, "priceUsd")
    liq = num(pair, "liquidity", "usd")
    created = num(pair, "pairCreatedAt") / 1000.0
    age_min = (now - created) / 60.0 if created > 0 else -1
    vol_h1 = num(pair, "volume", "h1")
    buys = num(pair, "txns", "h1", "buys")
    sells = num(pair, "txns", "h1", "sells")
    ch_m5 = num(pair, "priceChange", "m5")
    ch_h1 = num(pair, "priceChange", "h1")
    fdv = num(pair, "fdv")

    if price <= 0:
        return False, 0, "no price"
    if liq < c["min_liquidity"]:
        return False, 0, "liquidity too low"
    if age_min < c["min_age_min"]:
        return False, 0, "too new or age unknown"
    if age_min > c["max_age_h"] * 60:
        return False, 0, "too old"
    if not c["fdv_min"] <= fdv <= c["fdv_max"]:
        return False, 0, "valuation out of range"
    if vol_h1 < c["min_vol_h1"]:
        return False, 0, "volume too low"
    if vol_h1 > c["max_vol_to_liq"] * liq:
        return False, 0, "volume looks fake for this liquidity"
    if buys + sells < c["min_txns_h1"]:
        return False, 0, "too few trades"
    if sells < c["min_sell_share"] * (buys + sells):
        return False, 0, "almost no sells (possible honeypot)"
    if buys < c["min_buy_ratio"] * sells:
        return False, 0, "not enough buying"
    if not c["h1_change_min"] <= ch_h1 <= c["h1_change_max"]:
        return False, 0, "1h move out of range"
    if ch_m5 <= 0:
        return False, 0, "falling right now"

    score = (buys / max(sells, 1.0)) * 10 + min(vol_h1 / liq, 5) * 5 + min(ch_h1, 60) / 4
    reason = "1h +%.0f%%, buys/sells %.1f, liq $%.0fk, age %.1fh" % (ch_h1, buys / max(sells, 1.0), liq / 1000, age_min / 60)
    return True, round(score, 1), reason


def load_state(path):
    try:
        with open(path) as fh:
            state = json.load(fh)
        if isinstance(state, dict) and "cash" in state:
            return state
    except (OSError, ValueError):
        pass
    return {"cash": CFG["start_cash"], "positions": [], "closed": [], "equity": [], "cooldown": {}, "runs": 0}


def close(state, pos, price, why, now):
    proceeds = pos["qty"] * price * (1 - CFG["slippage"])
    state["cash"] += proceeds
    state["closed"].insert(0, {
        "symbol": pos["symbol"], "address": pos["address"], "url": pos["url"],
        "entry_time": pos["entry_time"], "exit_time": now,
        "entry_price": pos["entry_price"], "exit_price": price,
        "cost": pos["cost"], "pnl": round(proceeds - pos["cost"], 2),
        "pnl_pct": round((proceeds / pos["cost"] - 1) * 100, 1), "why": why,
    })
    state["cooldown"][pos["address"]] = now
    print("SELL %s: %s, pnl %.2f" % (pos["symbol"], why, proceeds - pos["cost"]))


def run(out_dir, now=None):
    now = now or time.time()
    c = CFG
    path = os.path.join(out_dir, "data.json")
    state = load_state(path)
    state["runs"] = state.get("runs", 0) + 1

    addresses = candidate_addresses()
    open_addresses = [p["address"] for p in state["positions"]]
    pairs = best_pairs(list(dict.fromkeys(open_addresses + addresses)))
    api_ok = bool(pairs) or not (addresses or open_addresses)

    # 1. manage open paper positions
    still_open = []
    for pos in state["positions"]:
        pair = pairs.get(pos["address"])
        if pair is None or num(pair, "priceUsd") <= 0:
            pos["misses"] = pos.get("misses", 0) + 1
            if api_ok and pos["misses"] >= 3:
                close(state, pos, 0.0, "no market data (possible rug)", now)
            else:
                still_open.append(pos)
            continue
        pos["misses"] = 0
        price = num(pair, "priceUsd")
        liq = num(pair, "liquidity", "usd")
        pos["last_price"] = price
        pos["peak_price"] = max(pos.get("peak_price", price), price)
        change = price / pos["entry_price"] - 1
        peak = pos["peak_price"] / pos["entry_price"] - 1
        held_h = (now - pos["entry_time"]) / 3600.0

        if liq < 2000 or liq < 0.3 * pos["entry_liq"]:
            close(state, pos, price * 0.5, "liquidity pulled", now)
        elif change >= c["take_profit"]:
            close(state, pos, price, "take profit", now)
        elif change <= -c["stop_loss"]:
            close(state, pos, price, "stop loss", now)
        elif peak >= c["trail_arm"] and price <= pos["peak_price"] * (1 - c["trail_drop"]):
            close(state, pos, price, "trailing stop", now)
        elif held_h >= c["max_hold_h"]:
            close(state, pos, price, "time limit", now)
        else:
            still_open.append(pos)
    state["positions"] = still_open

    # 2. look for new paper buys
    state["cooldown"] = {a: t for a, t in state["cooldown"].items() if now - t < c["cooldown_h"] * 3600}
    held = {p["address"] for p in state["positions"]}
    passed, rejected = [], {}
    for address in addresses:
        pair = pairs.get(address)
        if pair is None or address in held or address in state["cooldown"]:
            continue
        ok, score, reason = check(pair, now)
        if ok:
            passed.append((score, address, pair, reason))
        else:
            rejected[reason] = rejected.get(reason, 0) + 1
    passed.sort(key=lambda x: -x[0])

    for score, address, pair, reason in passed:
        if len(state["positions"]) >= c["max_open"] or state["cash"] < c["stake"]:
            break
        price = num(pair, "priceUsd") * (1 + c["slippage"])
        base = pair.get("baseToken") or {}
        state["positions"].append({
            "address": address, "symbol": str(base.get("symbol", "?"))[:20], "name": str(base.get("name", ""))[:40],
            "url": pair.get("url") or "https://dexscreener.com/%s/%s" % (CHAIN, address),
            "entry_price": price, "last_price": num(pair, "priceUsd"), "peak_price": num(pair, "priceUsd"),
            "qty": c["stake"] / price, "cost": c["stake"], "entry_time": now,
            "entry_liq": num(pair, "liquidity", "usd"), "score": score, "reason": reason, "misses": 0,
        })
        state["cash"] -= c["stake"]
        print("BUY %s: %s" % (base.get("symbol"), reason))

    # 3. bookkeeping for the page
    equity = state["cash"] + sum(p["qty"] * p.get("last_price", p["entry_price"]) for p in state["positions"])
    state["equity"].append([int(now), round(equity, 2)])
    state["equity"] = state["equity"][-1500:]
    state["closed"] = state["closed"][:300]
    wins = [t for t in state["closed"] if t["pnl"] > 0]
    state["summary"] = {
        "updated": int(now), "chain": CHAIN, "start_cash": c["start_cash"], "equity": round(equity, 2),
        "cash": round(state["cash"], 2), "trades": len(state["closed"]), "wins": len(wins),
        "win_rate": round(100.0 * len(wins) / len(state["closed"]), 1) if state["closed"] else None,
        "scanned": len(addresses), "passed": len(passed), "api_ok": api_ok,
        "rejected": sorted(rejected.items(), key=lambda x: -x[1])[:6],
    }
    state["config"] = c

    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w") as fh:
        json.dump(state, fh, indent=1)
    print("equity %.2f, open %d, closed %d, scanned %d, passed %d" % (equity, len(state["positions"]), len(state["closed"]), len(addresses), len(passed)))
    return state


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "out")
