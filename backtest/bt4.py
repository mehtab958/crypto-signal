#!/usr/bin/env python3
"""Binary-option test: do any of the 13 strategies win often enough to beat a Quotex-style payout?
Signal on a closed candle, entry at the next 1-minute open, result = price after the expiry.
Break-even win rate: 80% payout -> 55.6%, 90% payout -> 52.6%. Ties (no change) are left out."""
import sys, time, json, urllib.request
import backtest as B

def fetch(symbol, days):
    end = int(time.time() // 60 * 60 * 1000); t = end - days * 86400 * 1000; out = []
    while t < end:
        rows = B.get("https://data-api.binance.vision/api/v3/klines?symbol=%s&interval=1m&limit=1000&startTime=%d" % (symbol, t))
        if not rows: break
        out += [(int(k[0]) // 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in rows]
        t = rows[-1][0] + 60000
    return out

def run(m1, tf, expiry, htf, split, gold):
    m1i = {b[0]: n for n, b in enumerate(m1)}
    bars = m1 if tf == 1 else B.agg(m1, tf)
    d = B.Ind(bars); ct = [b[0] + tf * 60 for b in bars]
    m15 = B.htf_trend(B.agg(m1, 15), ct); h1 = B.htf_trend(B.agg(m1, 60), ct)
    res = {}
    for name, fn in B.STRATS:
        a, b, busy = [0, 0], [0, 0], 0
        for i in range(110, len(bars) - 1):
            if ct[i] < busy or (gold and not B.gold_open(ct[i])): continue
            s = fn(d, i)
            if s == 0 or (htf and not (m15[i] == s and h1[i] == s)): continue
            k = m1i.get(ct[i])
            if k is None or k + expiry >= len(m1): continue
            entry, exit_ = m1[k][1], m1[k + expiry][1]
            busy = ct[i] + expiry * 60
            if exit_ == entry: continue
            win = (exit_ - entry) * s > 0
            box = a if ct[i] < split else b
            box[0] += 1; box[1] += win
        res[name] = (a, b)
    return res

DAYS = 60
for symbol, gold in (("PAXGUSDT", True), ("BTCUSDT", False)):
    m1 = fetch(symbol, DAYS); split = m1[0][0] + (m1[-1][0] - m1[0][0]) // 2
    print("\n######## %s (%s), %d one-minute candles, two halves of %d days" % (symbol, "gold" if gold else "bitcoin", len(m1), DAYS // 2))
    best = []
    for tf, expiry in ((1, 1), (1, 2), (1, 3), (1, 5), (5, 5), (5, 15), (15, 15)):
        for htf in (False, True):
            r = run(m1, tf, expiry, htf, split, gold)
            for name, (a, b) in r.items():
                if a[0] >= 30 and b[0] >= 30:
                    best.append((min(a[1] / a[0], b[1] / b[0]), name, tf, expiry, htf, a, b))
            sys.stdout.flush()
    best.sort(reverse=True)
    print("Top 12 by the WORSE of the two halves (needs 55.6%% at 80%% payout, 52.6%% at 90%%):")
    for w, name, tf, expiry, htf, a, b in best[:12]:
        print("  %-9s signal m%-2d expiry %2d min trend=%-5s  first half %4d trades %5.1f%% | second half %4d trades %5.1f%%" % (
            name, tf, expiry, htf, a[0], 100 * a[1] / a[0], b[0], 100 * b[1] / b[0]))
    allw = sum(x[5][1] + x[6][1] for x in best); alln = sum(x[5][0] + x[6][0] for x in best)
    print("All %d combinations together: %.1f%% won over %d trades" % (len(best), 100 * allw / alln, alln))
