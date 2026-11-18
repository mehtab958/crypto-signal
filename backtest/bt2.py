#!/usr/bin/env python3
"""Backtest of the Raja Banks SnR bot, the VSA bot and the combined Raja+VSA bot on
gold prices (PAXG, 1 oz = 0.01 lot of XAUUSD), compared with the MACD setup.
Entries on 15-minute candles, storyline on 4-hour candles, exits checked on 1-minute
candles (stop assumed first when stop and target are inside the same candle).
Ported from the C# bots; self-learning and daily loss limits are not simulated."""
import json, sys, time
from datetime import datetime, timezone
import backtest as B

COST = 0.30
LOOKBACK = 300

class Lv:
    __slots__ = ("price", "res", "fresh", "uses", "flips", "born", "kind", "dead")
    def __init__(s, price, res, born, kind):
        s.price, s.res, s.born, s.kind = price, res, born, kind
        s.fresh, s.uses, s.flips, s.dead = True, 0, 0, False

def snr_walk(bars):
    """Walk candles forward (Malaysian SnR rules). Returns per-bar rejection event
    (dir, price, kind) or None, and per-bar list of alive levels after that bar."""
    O = [b[1] for b in bars]; H = [b[2] for b in bars]; L = [b[3] for b in bars]; C = [b[4] for b in bars]
    levels, events, alive = [], [None] * len(bars), [None] * len(bars)
    for j in range(len(bars)):
        if j < 22:
            alive[j] = []; continue
        o, c, h, l = O[j], C[j], H[j], L[j]
        ev = None
        for lv in levels:
            if lv.dead or lv.born >= j or lv.born < j - LOOKBACK: continue
            if lv.res:
                if c > lv.price: lv.res, lv.fresh, lv.kind = False, True, "RBS"; lv.flips += 1
                elif h >= lv.price:
                    if lv.fresh: ev = (-1, lv.price, lv.kind)
                    lv.fresh = False; lv.uses += 1
            else:
                if c < lv.price: lv.res, lv.fresh, lv.kind = True, True, "SBR"; lv.flips += 1
                elif l <= lv.price:
                    if lv.fresh: ev = (1, lv.price, lv.kind)
                    lv.fresh = False; lv.uses += 1
            if lv.uses > 2 or lv.flips > 2: lv.dead = True
        po, pc = O[j - 1], C[j - 1]
        pbull, pbear, cbull, cbear = pc > po, pc < po, c > o, c < o
        if pbull and cbear: levels.append(Lv(pc, True, j, "A"))
        elif pbear and cbull: levels.append(Lv(pc, False, j, "V"))
        elif (pbull and cbull) or (pbear and cbear):
            avg = sum(abs(C[k] - O[k]) for k in range(j - 21, j - 1)) / 20
            if avg > 0 and abs(pc - po) >= 1.5 * avg and abs(c - o) >= 1.5 * avg:
                levels.append(Lv(pc, cbear, j, "GAP"))
        events[j] = ev
        levels = [lv for lv in levels if not lv.dead and lv.born >= j - LOOKBACK]
        alive[j] = [(lv.price, lv.res, lv.fresh) for lv in levels]
    return events, alive

def atr(bars, n=14):
    tr, out = [], []
    for i, b in enumerate(bars):
        pc = bars[i - 1][4] if i else b[4]
        tr.append(max(b[2] - b[3], abs(b[2] - pc), abs(b[3] - pc)))
        out.append(sum(tr[max(0, i - n + 1):i + 1]) / min(i + 1, n))
    return out

def vsa_read(d, i, trend, extra_bars):
    """VSA reading as in the bots. extra_bars=True adds the RajaVsa demand/supply bar."""
    av = sum(d.V[i - 20:i]) / 20; asp = sum(d.H[j] - d.L[j] for j in range(i - 20, i)) / 20
    hi20, lo20 = max(d.H[i - 20:i]), min(d.L[i - 20:i])
    h, l, c, v = d.H[i], d.L[i], d.C[i], d.V[i]; sp = h - l
    if sp <= 0 or av <= 0 or asp <= 0: return 0, ""
    cp = (c - l) / sp; up, dn = c > d.C[i - 1], c < d.C[i - 1]
    hv, lv = v >= 2.0 * av, v <= 0.8 * av; wide, narrow = sp >= 1.3 * asp, sp <= 0.7 * asp
    if dn and hv and wide and cp >= .5 and l <= lo20: return 1, "stopping volume"
    if l < lo20 and c > lo20 and cp >= .6 and v >= 1.2 * av: return 1, "spring"
    if up and hv and wide and cp <= .5 and h >= hi20: return -1, "buying climax"
    if h > hi20 and c < hi20 and cp <= .4 and v >= 1.2 * av: return -1, "upthrust"
    if hv and narrow:
        if up and c > d.C[i - 5]: return -1, "effort no result"
        if dn and c < d.C[i - 5]: return 1, "effort no result"
    quieter = v < d.V[i - 1] and v < d.V[i - 2]
    if dn and narrow and lv and quieter and c > trend[i]: return 1, "no supply"
    if up and narrow and lv and quieter and c < trend[i]: return -1, "no demand"
    if extra_bars:
        if v >= 1.3 * av and cp >= .65: return 1, "demand bar"
        if v >= 1.3 * av and cp <= .35: return -1, "supply bar"
    return 0, ""

def candidates(m1, sys_name, fixed_rr=None, need_vsa=False):
    """Signals as (time, dir, risk, reward, key, label)."""
    m15 = B.agg(m1, 15); h4 = B.agg(m1, 240)
    d = B.Ind(m15); tr = d.e50; a = atr(m15)
    ct = [b[0] + 900 for b in m15]
    out = []
    if sys_name in ("raja", "rajavsa"):
        ev15, _ = snr_walk(m15)
        ev4, alive4 = snr_walk(h4)
        h4close = [b[0] + 14400 for b in h4]
        last_ev4 = []  # most recent H4 event index up to each H4 bar
        le = -1
        for k in range(len(h4)):
            if ev4[k]: le = k
            last_ev4.append(le)
        k = -1
        for i in range(40, len(m15) - 1):
            while k + 1 < len(h4) and h4close[k + 1] <= ct[i]: k += 1
            if k < 40 or not B.gold_open(ct[i]): continue
            e4 = last_ev4[k]
            if e4 < 0 or k - e4 > 12: continue
            story = ev4[e4][0]
            ev = ev15[i]
            if not ev or ev[0] != story: continue
            label = ev[2]
            if need_vsa:
                vn, nn = vsa_read(d, i, tr, True); vb, nb = vsa_read(d, i - 1, tr, True)
                if vn == story: label += "+" + nn
                elif vb == story and vn == 0: label += "+" + nb
                else: continue
            buf = a[i] * 0.25
            stop = d.L[i] - buf if story > 0 else d.H[i] + buf
            price = m15[i + 1][1]
            risk = abs(price - stop)
            if risk <= 0 or risk > 10: continue
            if fixed_rr:
                reward = risk * fixed_rr
            else:
                ahead = [p for p, res, fr in alive4[k] if fr and ((story > 0 and res and p > price) or (story < 0 and not res and p < price))]
                if ahead:
                    reward = min(abs(p - price) for p in ahead)
                    if reward / risk < 1.5: continue
                else:
                    reward = risk * 2.0
            out.append((ct[i], story, risk, reward, round(ev[1], 5), label))
    elif sys_name == "vsa":
        for i in range(60, len(m15) - 1):
            if not B.gold_open(ct[i]): continue
            s, name = vsa_read(d, i - 1, tr, False)
            if s == 0: continue
            if not ((s > 0 and d.C[i] > d.C[i - 1]) or (s < 0 and d.C[i] < d.C[i - 1])): continue
            buf = a[i] * 0.25
            stop = min(d.L[i - 1], d.L[i]) - buf if s > 0 else max(d.H[i - 1], d.H[i]) + buf
            price = m15[i + 1][1]; risk = abs(price - stop)
            if risk <= 0 or risk > 5 or 0.2 > 0.3 * risk: continue
            out.append((ct[i], s, risk, 2 * risk, None, name))
    elif sys_name == "macd":
        m15t = B.htf_trend(m15, ct); h1t = B.htf_trend(B.agg(m1, 60), ct)
        for i in range(110, len(m15) - 1):
            if not B.gold_open(ct[i]): continue
            s = B.macd(d, i)
            if s == 0 or m15t[i] != s or h1t[i] != s: continue
            out.append((ct[i], s, 3.0, 6.0, None, "macd"))
    return out

def sim(m1, m1i, t, s, risk, reward, breakeven):
    i = m1i.get(t)
    if i is None: return None
    entry = m1[i][1]; stop = entry - risk * s; tgt = entry + reward * s; be = False
    for k in range(i, min(len(m1), i + 3 * 1440)):
        _, o, h, l, c, v = m1[k]
        worst, best = (l, h) if s > 0 else (h, l)
        if (worst - stop) * s <= 0: return (stop - entry) * s - COST, m1[k][0]
        if (best - tgt) * s >= 0: return reward - COST, m1[k][0]
        if breakeven and not be and (best - entry) * s >= risk: stop, be = entry, True
    k = min(len(m1), i + 3 * 1440) - 1
    return (m1[k][4] - entry) * s - COST, m1[k][0]

def portfolio(m1, m1i, cands, max_open, breakeven_for):
    """Takes signals in time order, at most max_open at once, each level used once."""
    cands = sorted(cands, key=lambda x: x[0]); used, open_until, trades = set(), [], []
    for t, s, risk, reward, key, label, src in cands:
        open_until = [u for u in open_until if u > t]
        if len(open_until) >= max_open: continue
        if key is not None and (src, key) in used: continue
        r = sim(m1, m1i, t, s, risk, reward, src in breakeven_for)
        if r is None: continue
        if key is not None: used.add((src, key))
        open_until.append(r[1]); trades.append((t, r[0], src, label))
    return trades

def stats(tr):
    n = len(tr); w = sum(1 for x in tr if x[1] > 0)
    return "%4d trades %3d%% won  net %+7.1f" % (n, round(100 * w / n) if n else 0, sum(x[1] for x in tr))

if __name__ == "__main__":
    B.DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 95
    m1 = B.fetch(); m1i = {b[0]: n for n, b in enumerate(m1)}
    t0, t1 = m1[0][0], m1[-1][0]
    test_start = t0 + 5 * 86400          # first 5 days only warm up the indicators
    mid = t1 - 45 * 86400                # older part vs the 45 days used to pick MACD
    print("candles %d, %s to %s" % (len(m1), datetime.fromtimestamp(t0, timezone.utc), datetime.fromtimestamp(t1, timezone.utc)))
    print("A = older period (%s to %s), B = last 45 days (used to pick MACD). Cost $%.2f per trade, 0.01 lot.\n" % (
        datetime.fromtimestamp(test_start, timezone.utc).date(), datetime.fromtimestamp(mid, timezone.utc).date(), COST))
    C = {}
    C["macd"] = [x + ("macd",) for x in candidates(m1, "macd")]
    C["raja 1:3"] = [x + ("raja",) for x in candidates(m1, "raja", fixed_rr=3.0)]
    C["raja level target"] = [x + ("raja",) for x in candidates(m1, "raja")]
    C["raja+vsa (bot default)"] = [x + ("rajavsa",) for x in candidates(m1, "rajavsa", need_vsa=True)]
    C["raja+vsa 1:3"] = [x + ("rajavsa",) for x in candidates(m1, "rajavsa", fixed_rr=3.0, need_vsa=True)]
    C["vsa 1:2"] = [x + ("vsa",) for x in candidates(m1, "vsa")]
    for k in C: C[k] = [x for x in C[k] if x[0] >= test_start]
    runs = [
        ("MACD (bot now)", C["macd"], 1),
        ("Raja SnR 1:3", C["raja 1:3"], 2),
        ("Raja SnR level target", C["raja level target"], 2),
        ("Raja+VSA (bot default)", C["raja+vsa (bot default)"], 2),
        ("Raja+VSA 1:3", C["raja+vsa 1:3"], 2),
        ("VSA bot 1:2", C["vsa 1:2"], 1),
        ("MERGED MACD + Raja+VSA, 1 at a time", C["macd"] + C["raja+vsa (bot default)"], 1),
        ("MERGED MACD + Raja+VSA 1:3, 1 at a time", C["macd"] + C["raja+vsa 1:3"], 1),
        ("MERGED MACD + VSA, 1 at a time", C["macd"] + C["vsa 1:2"], 1),
    ]
    be = {"raja", "rajavsa", "vsa"}
    res = {}
    for name, cands, mx in runs:
        tr = portfolio(m1, m1i, cands, mx, be)
        a = [x for x in tr if x[0] < mid]; b = [x for x in tr if x[0] >= mid]
        print("%-42s A: %s | B: %s | ALL: %s" % (name, stats(a), stats(b), stats(tr)))
        if name.startswith("MERGED"):
            for src in ("macd", "rajavsa", "vsa"):
                part = [x for x in tr if x[2] == src]
                if part: print("%42s   of which %-8s %s" % ("", src, stats(part)))
        res[name] = tr
        sys.stdout.flush()
    # breakdown of the combined bot by level type and VSA signal
    tr = res["Raja+VSA (bot default)"]
    print("\nRaja+VSA trades by level type / VSA signal:")
    groups = {}
    for x in tr:
        lvl, _, v = x[3].partition("+")
        groups.setdefault("level " + lvl, []).append(x); groups.setdefault("vsa " + v, []).append(x)
    for g in sorted(groups): print("  %-24s %s" % (g, stats(groups[g])))
    print("\nRaja+VSA exits: target %d, stop %d, break-even %d" % (
        sum(1 for x in tr if x[1] > 0), sum(1 for x in tr if x[1] < -COST - 0.01), sum(1 for x in tr if abs(x[1] + COST) < 0.01)))
