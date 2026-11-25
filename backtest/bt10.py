#!/usr/bin/env python3
"""Walk-forward search for a fast gold scalper (PAXG = 1 oz = 0.01 lot XAUUSD).
Signals: the 13 strategies on 3- and 5-minute candles. Exits: stop = k x ATR(14), target = R x stop,
max hold 4 h. Filters: 15-min + 1-hour trend (on/off), London+New York hours 07-17 UTC (on/off).
Costs $0.30 per trade. Inside a 1-minute candle the path is open-low-high-close (green) or
open-high-low-close (red). Periods: P1 = first third (used to PICK), P2 and P3 = later thirds (CHECK)."""
import sys, time
from datetime import datetime, timezone
import backtest as B, bt2

COST = 0.30
B.DAYS = 186
m1 = B.fetch(); n1 = len(m1)
idx = {b[0]: k for k, b in enumerate(m1)}
t0, t1 = m1[0][0] + 5 * 86400, m1[-1][0]
p_edges = [t0 + (t1 - t0) * k // 3 for k in range(4)]
def period(t): return 0 if t < p_edges[1] else (1 if t < p_edges[2] else 2)
print("candles %d | P1 %s..%s  P2 ..%s  P3 ..%s" % (n1, *[datetime.fromtimestamp(x, timezone.utc).date() for x in p_edges]))

def exit_trade(k, s, stop_d, tgt_d, limit=240):
    e = m1[k][1]; stop = e - s * stop_d; tgt = e + s * tgt_d
    for j in range(k, min(n1, k + limit)):
        _, o, h, l, c, v = m1[j]
        for p in ((l, h) if c >= o else (h, l)):
            if (p - stop) * s <= 0: return -stop_d, j
            if (p - tgt) * s >= 0: return tgt_d, j
    j = min(n1, k + limit) - 1
    return (m1[j][4] - e) * s, j

results = []
for tf in (3, 5):
    bars = B.agg(m1, tf); d = B.Ind(bars); a = bt2.atr(bars)
    ct = [b[0] + tf * 60 for b in bars]
    m15 = B.htf_trend(B.agg(m1, 15), ct); h1 = B.htf_trend(B.agg(m1, 60), ct)
    for name, fn in B.STRATS:
        sig = []
        for i in range(110, len(bars) - 1):
            if ct[i] < t0 or not B.gold_open(ct[i]): continue
            s = fn(d, i)
            if s and ct[i] in idx: sig.append((ct[i], s, a[i], m15[i] == s and h1[i] == s, 7 <= datetime.fromtimestamp(ct[i], timezone.utc).hour < 17))
        for htf in (False, True):
            for sess in (False, True):
                for k_sl in (1.0, 1.5):
                    for R in (1.0, 2.0):
                        per = [[], [], []]; busy = 0
                        for t, s, atr_v, trend_ok, sess_ok in sig:
                            if t < busy or (htf and not trend_ok) or (sess and not sess_ok) or atr_v <= 0: continue
                            k = idx[t]; pnl, j = exit_trade(k, s, k_sl * atr_v, R * k_sl * atr_v)
                            busy = m1[j][0] + 60
                            per[period(t)].append(pnl - COST)
                        results.append(((tf, name, htf, sess, k_sl, R), per))
        sys.stdout.flush()
    print("tf %d done, %d setups so far" % (tf, len(results))); sys.stdout.flush()

# current GoldSweep for reference: m5 sweep, trend filter, fixed $6 / $3
bars = B.agg(m1, 5); d = B.Ind(bars); ct = [b[0] + 300 for b in bars]
m15 = B.htf_trend(B.agg(m1, 15), ct); h1 = B.htf_trend(B.agg(m1, 60), ct)
per = [[], [], []]; busy = 0
for i in range(110, len(bars) - 1):
    if ct[i] < t0 or ct[i] < busy or not B.gold_open(ct[i]) or ct[i] not in idx: continue
    s = B.sweep(d, i)
    if s == 0 or not (m15[i] == s and h1[i] == s): continue
    pnl, j = exit_trade(idx[ct[i]], s, 3.0, 6.0); busy = m1[j][0] + 60; per[period(ct[i])].append(pnl - COST)

def st(x):
    if not x: return "   0 tr            "
    return "%4d tr %3d%% %+7.1f" % (len(x), round(100 * sum(1 for p in x if p > 0) / len(x)), sum(x))
days = (t1 - t0) / 86400 / 3
print("\nReference, current GoldSweep: P1 %s | P2 %s | P3 %s" % (st(per[0]), st(per[1]), st(per[2])))

ok = [(c, p) for c, p in results if len(p[0]) >= 40]
ok.sort(key=lambda x: -sum(x[1][0]) / len(x[1][0]))
print("\nTop 15 setups PICKED on P1 (net per trade), then checked on P2 and P3 (%.0f days each):" % days)
print("%-44s %22s | %22s | %22s" % ("setup", "P1 (picked)", "P2 (check)", "P3 (check)"))
for (tf, name, htf, sess, k_sl, R), p in ok[:15]:
    lab = "m%d %-9s trend=%-3s hours=%-3s stop %.1fATR %.0fR" % (tf, name, "on" if htf else "off", "LN" if sess else "all", k_sl, R)
    print("%-44s %s | %s | %s   %.1f trades/day" % (lab, st(p[0]), st(p[1]), st(p[2]), sum(len(x) for x in p) / (3 * days)))
pos1 = [p for c, p in ok if sum(p[0]) > 0]
both = [p for p in pos1 if len(p[1]) and len(p[2]) and sum(p[1]) > 0 and sum(p[2]) > 0]
base = [p for c, p in ok if len(p[1]) and len(p[2]) and sum(p[1]) > 0 and sum(p[2]) > 0]
print("\nSetups with 40+ trades in P1: %d. Profitable in P1: %d. Of those, profitable in BOTH P2 and P3: %d (%.0f%%)." % (len(ok), len(pos1), len(both), 100 * len(both) / max(1, len(pos1))))
print("For comparison, share of ALL setups profitable in both P2 and P3: %.0f%%" % (100 * len(base) / max(1, len(ok))))
allpos = [(c, p) for c, p in ok if all(len(x) >= 25 and sum(x) > 0 for x in p)]
allpos.sort(key=lambda x: -min(sum(y) / len(y) for y in x[1]))
print("\nSetups profitable in ALL THREE periods (25+ trades each): %d" % len(allpos))
for (tf, name, htf, sess, k_sl, R), p in allpos[:12]:
    lab = "m%d %-9s trend=%-3s hours=%-3s stop %.1fATR %.0fR" % (tf, name, "on" if htf else "off", "LN" if sess else "all", k_sl, R)
    print("%-44s %s | %s | %s   %.1f trades/day" % (lab, st(p[0]), st(p[1]), st(p[2]), sum(len(x) for x in p) / (3 * days)))
