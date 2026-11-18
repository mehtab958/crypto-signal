#!/usr/bin/env python3
"""Deriv synthetic indices test: Boom 1000, Crash 1000 (spikes) and Volatility 100.
Data: Deriv's public API, 1-minute candles. Results are GROSS (before spread, swap and
commission) in index points, so any real cost only makes them worse.
Each result is shown for two separate halves of the period."""
import asyncio, json, sys, time, statistics
import websockets
import backtest as B

URLS = ["wss://ws.derivws.com/websockets/v3?app_id=1089", "wss://ws.binaryws.com/websockets/v3?app_id=1089",
        "wss://api.derivws.com/trading/v1/options/ws/public"]
DAYS = 40

async def fetch(symbol):
    for url in URLS:
        try:
            async with websockets.connect(url, open_timeout=20, max_size=2 ** 25) as ws:
                out, end = [], "latest"
                start_limit = int(time.time()) - DAYS * 86400
                for _ in range(40):
                    await ws.send(json.dumps({"ticks_history": symbol, "style": "candles", "granularity": 60, "count": 5000, "end": end}))
                    msg = json.loads(await asyncio.wait_for(ws.recv(), 30))
                    if msg.get("error"):
                        print(symbol, url, "error:", msg["error"].get("message")); break
                    c = msg.get("candles") or []
                    if not c: break
                    out = [(int(k["epoch"]), float(k["open"]), float(k["high"]), float(k["low"]), float(k["close"]), 1.0) for k in c] + out
                    if out[0][0] <= start_limit: break
                    end = out[0][0] - 1
                out = sorted({b[0]: b for b in out if b[0] >= start_limit}.values())
                if len(out) > 1000:
                    print("%s: %d candles from %s" % (symbol, len(out), url)); return out
        except Exception as e:
            print(symbol, url, "failed:", e)
    return []

def halves(trades, split):
    a = [p for t, p in trades if t < split]; b = [p for t, p in trades if t >= split]
    f = lambda x: "%5d trades %3d%% won net %+9.1f pts" % (len(x), round(100 * sum(1 for p in x if p > 0) / len(x)) if x else 0, sum(x))
    return "first half: %s | second half: %s" % (f(a), f(b))

def spike_tests(m1, up, label):
    """up=True for Boom (spikes up), False for Crash (spikes down)."""
    sign = 1 if up else -1
    moves = [(b[4] - b[1]) * sign for b in m1]
    typical = statistics.median(abs(x) for x in moves) or 1e-9
    spike = [(b[2] - b[1] if up else b[1] - b[3]) > 15 * typical for b in m1]
    n_sp = sum(spike); split = m1[len(m1) // 2][0]
    print("\n==== %s: %d candles, %d spike candles (one every %.0f minutes), typical 1-minute move %.3f pts" % (label, len(m1), n_sp, len(m1) / max(n_sp, 1), typical))
    since = 0
    quiet = []
    for i in range(len(m1)):
        quiet.append(since); since = 0 if spike[i] else since + 1
    def run(entry_rule, side, hold, stop_on_spike):
        trades, busy = [], 0
        for i in range(30, len(m1) - hold - 1):
            if i < busy or not entry_rule(i): continue
            entry = m1[i + 1][1]; exit_ = m1[i + hold][4]
            for k in range(i + 1, i + hold + 1):
                if spike[k]:
                    # spike in our favour if we are on the spike side; adverse otherwise
                    exit_ = m1[k][4] if (side == sign or stop_on_spike) else exit_
                    if side == sign or stop_on_spike: break
            trades.append((m1[i][0], (exit_ - entry) * side)); busy = i + hold + 1
        return trades
    spike_side, drift_side = sign, -sign
    tests = [
        ("catch spike: enter after 30 quiet min, hold up to 30", lambda i: quiet[i] >= 30, spike_side, 30, False),
        ("catch spike: enter after 60 quiet min, hold up to 60", lambda i: quiet[i] >= 60, spike_side, 60, False),
        ("catch spike: enter right after a spike, hold up to 30", lambda i: spike[i], spike_side, 30, False),
        ("ride the drift: enter after a spike, hold 10, stop on spike", lambda i: spike[i], drift_side, 10, True),
        ("ride the drift: enter anytime, hold 5, stop on spike", lambda i: True, drift_side, 5, True),
        ("ride the drift: enter after 30 quiet min, hold 15, stop on spike", lambda i: quiet[i] >= 30, drift_side, 15, True),
    ]
    for name, rule, side, hold, stop in tests:
        print("  %-62s %s" % (name, halves(run(rule, side, hold, stop), split)))

def strategy_tests(m1, label):
    split = m1[len(m1) // 2][0]
    print("\n==== %s: our 13 strategies as rise/fall trades (direction after the expiry; 50%% = coin flip)" % label)
    for tf, expiry in ((1, 5), (5, 15), (15, 60)):
        bars = m1 if tf == 1 else B.agg(m1, tf)
        d = B.Ind(bars); idx = {b[0]: n for n, b in enumerate(m1)}
        rows = []
        for name, fn in B.STRATS:
            if name.startswith("vol"): continue      # synthetic indices have no volume
            tr, busy = [], 0
            for i in range(110, len(bars) - 1):
                t = bars[i][0] + tf * 60
                if t < busy: continue
                s = fn(d, i)
                if s == 0: continue
                k = idx.get(t)
                if k is None or k + expiry >= len(m1): continue
                tr.append((t, (m1[k + expiry][1] - m1[k][1]) * s)); busy = t + expiry * 60
            rows.append((name, tr))
        print("  signals on m%d, expiry %d min" % (tf, expiry))
        for name, tr in rows:
            print("    %-9s %s" % (name, halves(tr, split)))

async def main():
    data = {}
    for sym in ("BOOM1000", "CRASH1000", "R_100"):
        data[sym] = await fetch(sym)
    if data["BOOM1000"]: spike_tests(data["BOOM1000"], True, "Boom 1000")
    if data["CRASH1000"]: spike_tests(data["CRASH1000"], False, "Crash 1000")
    if data["R_100"]: strategy_tests(data["R_100"], "Volatility 100")
    for sym in ("BOOM1000", "CRASH1000"):
        if data[sym]: strategy_tests(data[sym], sym)

asyncio.run(main())
