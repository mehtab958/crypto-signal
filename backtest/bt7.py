#!/usr/bin/env python3
"""Every-candle gold bot: one trade at the open of every candle, closed at +$0.40 or -$0.70 NET
(0.01 lot = 1 oz). Spread + commission per trade = COST, so price must move 0.40+COST to win
and only 0.70-COST to lose. Inside a 1-minute candle the path is assumed open-low-high-close
for green candles and open-high-low-close for red ones."""
import time
import backtest as B

def fetch_days(days):
    now = int(time.time() // 60 * 60 * 1000); t = now - days * 86400 * 1000; out = []
    while t < now:
        rows = B.get("https://data-api.binance.vision/api/v3/klines?symbol=PAXGUSDT&interval=1m&limit=1000&startTime=%d" % t)
        if not rows: break
        out += [(int(k[0]) // 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in rows]
        t = rows[-1][0] + 60000
    return out

def trade(m1, k, s, up, down, limit=600):
    """Long (s=1) or short (s=-1) from the open of 1m candle k. Returns +1 win, -1 loss, 0 timeout."""
    e = m1[k][1]
    for j in range(k, min(len(m1), k + limit)):
        _, o, h, l, c, v = m1[j]
        path = (l, h) if c >= o else (h, l)
        for p in path:
            if (p - e) * s >= up: return 1
            if (e - p) * s >= down: return -1
    return 0

m1 = fetch_days(30)
idx = {b[0]: n for n, b in enumerate(m1)}
days = (m1[-1][0] - m1[0][0]) / 86400
print("gold (PAXG) 1-minute candles: %d over %.0f days\n" % (len(m1), days))
for cost in (0.15, 0.25):
    up, down = 0.40 + cost, 0.70 - cost
    print("== costs $%.2f per trade: price must move +$%.2f to win $0.40, only -$%.2f to lose $0.70. Break-even win rate: 63.6%%" % (cost, up, down))
    for tf in (1, 5):
        bars = m1 if tf == 1 else B.agg(m1, tf)
        trend = B.htf_trend(B.agg(m1, 15), [b[0] for b in bars])
        for rule in ("same as last candle", "opposite of last candle", "with 15-min trend"):
            w = l = 0
            for i in range(1, len(bars)):
                if not B.gold_open(bars[i][0]): continue
                k = idx.get(bars[i][0])
                if k is None: continue
                last = bars[i - 1][4] - bars[i - 1][1]
                if rule == "same as last candle": s = 1 if last >= 0 else -1
                elif rule == "opposite of last candle": s = -1 if last >= 0 else 1
                else:
                    s = trend[i]
                    if s == 0: continue
                r = trade(m1, k, s, up, down)
                if r > 0: w += 1
                elif r < 0: l += 1
            n = w + l; net = w * 0.40 - l * 0.70
            print("   m%d, %-24s %6d trades (%3.0f/day)  won %4.1f%%  net $%+8.2f  ($%+.2f per day)" % (tf, rule, n, n / days, 100.0 * w / n, net, net / days))
    print()
