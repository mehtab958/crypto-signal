#!/usr/bin/env python3
"""5-minute Opening Range Breakout (ORB) on gold (PAXG = 1 oz, i.e. 0.01 lot of XAUUSD).
Range = high/low of the first 5 minutes after the session opens. Entry = first 5-minute candle that
CLOSES beyond the range, at the next minute's open. Stop = other side of the range (or its middle).
Target = R multiple; anything still open after the window closes at market. One trade per session per day.
Exits checked on 1-minute candles; stop assumed first if stop and target fall in the same candle.
Costs $0.30 per trade. Two halves of the period shown separately."""
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
import backtest as B

COST = 0.30
DAYS = 125

def fetch(days):
    now = int(time.time() // 60 * 60 * 1000); t = now - days * 86400 * 1000; out = []
    while t < now:
        rows = B.get("https://data-api.binance.vision/api/v3/klines?symbol=PAXGUSDT&interval=1m&limit=1000&startTime=%d" % t)
        if not rows: break
        out += [(int(k[0]) // 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4])) for k in rows]
        t = rows[-1][0] + 60000
    return out

SESSIONS = {"London open 08:00 London time": ("Europe/London", 8, 0, 240),
            "New York open 09:30 NY time": ("America/New_York", 9, 30, 240),
            "New York gold open 08:20 NY time": ("America/New_York", 8, 20, 240)}

def run(m1, idx, tz, hh, mm, window, rr, stop_mode, split, min_range=0.0, max_range=1e9):
    a, b = [], []
    first = datetime.fromtimestamp(m1[0][0], timezone.utc).date(); last = datetime.fromtimestamp(m1[-1][0], timezone.utc).date()
    d = first
    while d <= last:
        local = datetime(d.year, d.month, d.day, hh, mm, tzinfo=ZoneInfo(tz))
        t0 = int(local.timestamp()); d += timedelta(days=1)
        if local.weekday() >= 5 or t0 not in idx: continue
        k0 = idx[t0]
        rng = m1[k0:k0 + 5]
        if len(rng) < 5 or rng[-1][0] != t0 + 240: continue
        hi = max(x[2] for x in rng); lo = min(x[3] for x in rng); size = hi - lo
        if size <= 0 or size < min_range or size > max_range: continue
        end = t0 + window * 60
        k = k0 + 5; trade = None
        while k + 5 < len(m1) and m1[k][0] < end:
            c = m1[k + 4][4]                                  # close of this 5-minute candle
            if c > hi: trade = (1, k + 5); break
            if c < lo: trade = (-1, k + 5); break
            k += 5
        if not trade: continue
        s, ke = trade; entry = m1[ke][1]
        stop = (lo if s > 0 else hi) if stop_mode == "other side" else (hi + lo) / 2
        risk = (entry - stop) * s
        if risk <= 0: continue
        target = entry + rr * risk * s; pnl = None
        for j in range(ke, len(m1)):
            t, o, h, l, cl = m1[j]
            if t >= end: pnl = (m1[j][1] - entry) * s; break
            worst, best = (l, h) if s > 0 else (h, l)
            if (worst - stop) * s <= 0: pnl = -risk; break
            if (best - target) * s >= 0: pnl = rr * risk; break
        if pnl is None: continue
        (a if t0 < split else b).append((pnl - COST, (pnl - COST) / risk, size))
    return a, b

def fmt(x):
    if not x: return "   0 trades"
    w = sum(1 for p in x if p[0] > 0)
    return "%4d trades %3d%% won net $%+7.2f avg %+.2fR" % (len(x), round(100 * w / len(x)), sum(p[0] for p in x), sum(p[1] for p in x) / len(x))

m1 = fetch(DAYS)
idx = {b[0]: n for n, b in enumerate(m1)}
split = m1[0][0] + (m1[-1][0] - m1[0][0]) // 2
print("gold (PAXG) 1-minute candles: %d, %s to %s; halves split at %s\n" % (len(m1),
      datetime.fromtimestamp(m1[0][0], timezone.utc).date(), datetime.fromtimestamp(m1[-1][0], timezone.utc).date(),
      datetime.fromtimestamp(split, timezone.utc).date()))
for name, (tz, hh, mm, window) in SESSIONS.items():
    print("== %s (trade window %d min)" % (name, window))
    sizes = []
    for stop_mode in ("other side", "middle"):
        for rr in (1.0, 1.5, 2.0, 3.0):
            a, b = run(m1, idx, tz, hh, mm, window, rr, stop_mode, split)
            if not sizes: sizes = [p[2] for p in a + b]
            print("   stop=%-10s target %.1fR | first half: %s | second half: %s" % (stop_mode, rr, fmt(a), fmt(b)))
    if sizes:
        sizes.sort(); print("   opening range size: median $%.2f, middle half $%.2f to $%.2f" % (sizes[len(sizes) // 2], sizes[len(sizes) // 4], sizes[3 * len(sizes) // 4]))
    print()
