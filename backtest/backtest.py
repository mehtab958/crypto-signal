#!/usr/bin/env python3
"""Backtest of the gold bot's 13 strategies on real gold-backed token prices (PAXG = 1 oz gold).
0.01 lot of XAUUSD = 1 oz, so $1 of price move = $1 of profit, same as PAXG.
Signals are read on the chosen timeframe; exits are checked on 1-minute candles.
If target and stop are both inside one candle, the stop is assumed to come first."""
import json, sys, time, urllib.request
from datetime import datetime, timezone

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 45
COST = 0.30          # spread + commission per trade, in $ per oz (0.01 lot)
MAX_HOLD_MIN = 24 * 60

def get(url):
    for a in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "bt"}), timeout=30) as r:
                return json.loads(r.read())
        except Exception as e:
            print("retry", e); time.sleep(2 + a)
    raise SystemExit("data fetch failed")

def fetch():
    end = int(time.time() // 60 * 60 * 1000)
    start = end - DAYS * 86400 * 1000
    out, t = [], start
    while t < end:
        rows = get("https://data-api.binance.vision/api/v3/klines?symbol=PAXGUSDT&interval=1m&limit=1000&startTime=%d" % t)
        if not rows: break
        for k in rows:
            out.append((int(k[0]) // 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])))
        t = rows[-1][0] + 60000
    return out

def gold_open(ts):
    d = datetime.fromtimestamp(ts, timezone.utc)
    wd, h = d.weekday(), d.hour   # Mon=0
    if wd == 5: return False
    if wd == 4 and h >= 21: return False
    if wd == 6 and h < 22: return False
    return True

def agg(m1, mins):
    out, cur = [], None
    for t, o, h, l, c, v in m1:
        b = t - t % (mins * 60)
        if cur is None or cur[0] != b:
            if cur: out.append(cur)
            cur = [b, o, h, l, c, v]
        else:
            cur[2] = max(cur[2], h); cur[3] = min(cur[3], l); cur[4] = c; cur[5] += v
    if cur: out.append(cur)
    return [tuple(x) for x in out]

def ema(v, n):
    k, out, e = 2 / (n + 1), [], v[0]
    for i, x in enumerate(v):
        e = x if i == 0 else x * k + e * (1 - k); out.append(e)
    return out

def rsi(v, n):
    out, g, l = [50.0], 0.0, 0.0
    for i in range(1, len(v)):
        d = v[i] - v[i - 1]; up, dn = max(d, 0), max(-d, 0)
        if i <= n: g += up / n; l += dn / n
        else: g = (g * (n - 1) + up) / n; l = (l * (n - 1) + dn) / n
        out.append(50.0 if i < n else (100.0 if l == 0 else 100 - 100 / (1 + g / l)))
    return out

def sma(v, n):
    out, s = [], 0.0
    for i, x in enumerate(v):
        s += x
        if i >= n: s -= v[i - n]
        out.append(s / min(i + 1, n))
    return out

class Ind:
    def __init__(s, b):
        s.O = [x[1] for x in b]; s.H = [x[2] for x in b]; s.L = [x[3] for x in b]; s.C = [x[4] for x in b]; s.V = [x[5] for x in b]
        C = s.C
        s.e9, s.e21, s.e50 = ema(C, 9), ema(C, 21), ema(C, 50)
        s.r7, s.r14 = rsi(C, 7), rsi(C, 14)
        mid = sma(C, 20); s.bbU, s.bbL = [], []
        for i in range(len(C)):
            w = C[max(0, i - 19):i + 1]; m = sum(w) / len(w); sd = (sum((x - m) ** 2 for x in w) / len(w)) ** .5
            s.bbU.append(mid[i] + 2 * sd); s.bbL.append(mid[i] - 2 * sd)
        e12, e26 = ema(C, 12), ema(C, 26); s.macd = [a - b for a, b in zip(e12, e26)]; s.sig = ema(s.macd, 9)
        kraw = []
        for i in range(len(C)):
            hh = max(s.H[max(0, i - 13):i + 1]); ll = min(s.L[max(0, i - 13):i + 1])
            kraw.append(50 if hh == ll else (C[i] - ll) / (hh - ll) * 100)
        s.k = sma(kraw, 3); s.d = sma(s.k, 3)
    def hh(s, end, n): return max(s.H[end - n:end])
    def ll(s, end, n): return min(s.L[end - n:end])
    def av(s, end, n): return sum(s.V[end - n:end]) / n

def pullback(d, i):
    lo = min(d.r7[i-1], d.r7[i-2], d.r7[i-3]); hi = max(d.r7[i-1], d.r7[i-2], d.r7[i-3])
    C, O = d.C, d.O
    up = C[i] > d.e50[i] and d.e21[i] > d.e50[i]; dn = C[i] < d.e50[i] and d.e21[i] < d.e50[i]
    if up and lo < 35 and C[i] > O[i] and C[i] > d.e9[i] and d.r7[i] > d.r7[i-1]: return 1
    if dn and hi > 65 and C[i] < O[i] and C[i] < d.e9[i] and d.r7[i] < d.r7[i-1]: return -1
    return 0
def sweep(d, i):
    hi, lo = d.hh(i, 20), d.ll(i, 20)
    if d.L[i] < lo and d.C[i] > lo and d.C[i] > d.O[i]: return 1
    if d.H[i] > hi and d.C[i] < hi and d.C[i] < d.O[i]: return -1
    return 0
def pinbar(d, i):
    O, H, L, C = d.O[i], d.H[i], d.L[i], d.C[i]; body = abs(C - O); full = H - L
    if full <= 0: return 0
    lw = min(O, C) - L; uw = H - max(O, C); hi, lo = d.hh(i, 20), d.ll(i, 20); near = (hi - lo) * .15
    if lw >= 2 * body and lw >= .6 * full and L <= lo + near: return 1
    if uw >= 2 * body and uw >= .6 * full and H >= hi - near: return -1
    return 0
def engulf(d, i):
    O, C, p = d.O, d.C, i - 1
    if C[p] < O[p] and C[i] > O[i] and C[i] >= O[p] and O[i] <= C[p] and C[i] > d.e50[i]: return 1
    if C[p] > O[p] and C[i] < O[i] and C[i] <= O[p] and O[i] >= C[p] and C[i] < d.e50[i]: return -1
    return 0
def boll(d, i):
    C = d.C
    if C[i-1] < d.bbL[i-1] and C[i] > d.bbL[i] and d.r14[i-1] < 30: return 1
    if C[i-1] > d.bbU[i-1] and C[i] < d.bbU[i] and d.r14[i-1] > 70: return -1
    return 0
def cross(d, i):
    was = d.e9[i-1] - d.e21[i-1]; now = d.e9[i] - d.e21[i]
    if was <= 0 < now and d.C[i] > d.e50[i]: return 1
    if was >= 0 > now and d.C[i] < d.e50[i]: return -1
    return 0
def snr(d, i):
    C, H, L, O = d.C, d.H, d.L, d.O
    for j in range(i - 4, i - 101, -1):
        lv = C[j]
        if lv > C[j-1] and lv > C[j-2] and lv > C[j+1] and lv > C[j+2]:
            if not (H[i] >= lv and C[i] < lv and C[i] < O[i]): continue
            if all(H[m] < lv for m in range(j + 2, i)): return -1
        elif lv < C[j-1] and lv < C[j-2] and lv < C[j+1] and lv < C[j+2]:
            if not (L[i] <= lv and C[i] > lv and C[i] > O[i]): continue
            if all(L[m] > lv for m in range(j + 2, i)): return 1
    return 0
def fvg(d, i):
    C, H, L, O = d.C, d.H, d.L, d.O
    for a in range(i - 1, i - 13, -1):
        if L[a] > H[a-2]:
            top, bot = L[a], H[a-2]
            if all(L[m] > top for m in range(a + 1, i)) and L[i] <= top and C[i] > bot and C[i] > O[i]: return 1
        elif H[a] < L[a-2]:
            bot, top = H[a], L[a-2]
            if all(H[m] < bot for m in range(a + 1, i)) and H[i] >= bot and C[i] < top and C[i] < O[i]: return -1
    return 0
def retest(d, i):
    hi, lo = d.hh(i - 5, 20), d.ll(i - 5, 20)
    bu = any(d.C[j] > hi for j in range(i - 5, i)); bd = any(d.C[j] < lo for j in range(i - 5, i))
    if bu and not bd and d.L[i] <= hi and d.C[i] > hi and d.C[i] > d.O[i]: return 1
    if bd and not bu and d.H[i] >= lo and d.C[i] < lo and d.C[i] < d.O[i]: return -1
    return 0
def macd(d, i):
    was = d.macd[i-1] - d.sig[i-1]; now = d.macd[i] - d.sig[i]
    if was <= 0 < now and d.C[i] > d.e50[i]: return 1
    if was >= 0 > now and d.C[i] < d.e50[i]: return -1
    return 0
def stoch(d, i):
    was = d.k[i-1] - d.d[i-1]; now = d.k[i] - d.d[i]
    if was <= 0 < now and d.k[i-1] < 20: return 1
    if was >= 0 > now and d.k[i-1] > 80: return -1
    return 0
def volclimax(d, i):
    a = d.av(i, 20); full = d.H[i] - d.L[i]
    if a <= 0 or full <= 0 or d.V[i] < 2 * a: return 0
    lw = min(d.O[i], d.C[i]) - d.L[i]; uw = d.H[i] - max(d.O[i], d.C[i])
    if lw >= .5 * full and d.L[i] <= d.ll(i, 10): return 1
    if uw >= .5 * full and d.H[i] >= d.hh(i, 10): return -1
    return 0
def volbreak(d, i):
    a = d.av(i, 20)
    if a <= 0 or d.V[i] < 1.5 * a: return 0
    if d.C[i] > d.hh(i, 20) and d.C[i] > d.O[i]: return 1
    if d.C[i] < d.ll(i, 20) and d.C[i] < d.O[i]: return -1
    return 0

STRATS = [("pullback", pullback), ("sweep", sweep), ("pinbar", pinbar), ("engulf", engulf), ("bb", boll), ("cross", cross),
          ("snr", snr), ("fvg", fvg), ("retest", retest), ("macd", macd), ("stoch", stoch), ("volclimax", volclimax), ("volbreak", volbreak)]

def htf_trend(bars, ts_list):
    """For each timestamp, +1/-1/0 from the last CLOSED bar's close vs its EMA50."""
    e = ema([b[4] for b in bars], 50); out, j = {}, 0
    starts = [b[0] for b in bars]; width = bars[1][0] - bars[0][0]
    res = []
    for t in ts_list:
        while j + 1 < len(bars) and starts[j + 1] + width <= t: j += 1
        if starts[j] + width > t or j < 50: res.append(0)
        else: res.append(1 if bars[j][4] > e[j] else -1)
    return res

def simulate(m1, m1_index, entry_t, direction, tp, sl):
    """Enter at the open of the 1m candle starting at entry_t. Returns (pnl, exit_t)."""
    i = m1_index.get(entry_t)
    if i is None: return None
    entry = m1[i][1]
    tgt = entry + tp * direction; stp = entry - sl * direction
    for k in range(i, min(len(m1), i + MAX_HOLD_MIN)):
        t, o, h, l, c, v = m1[k]
        worst, best = (l, h) if direction > 0 else (h, l)
        if (worst - stp) * direction <= 0: return -sl - COST, t
        if (best - tgt) * direction >= 0: return tp - COST, t
    k = min(len(m1), i + MAX_HOLD_MIN) - 1
    return (m1[k][4] - entry) * direction - COST, m1[k][0]

def run(m1, tf, tp, sl, use_htf, split_t):
    m1i = {b[0]: n for n, b in enumerate(m1)}
    bars = m1 if tf == 1 else agg(m1, tf)
    d = Ind(bars); ts = [b[0] for b in bars]
    close_t = [t + tf * 60 for t in ts]   # signal known when the bar closes
    m15 = htf_trend(agg(m1, 15), close_t); h1 = htf_trend(agg(m1, 60), close_t)
    res = {}
    votes_by_bar = {}
    for name, fn in STRATS:
        trades, busy_until = [], 0
        for i in range(110, len(bars) - 1):
            if close_t[i] < busy_until or not gold_open(close_t[i]): continue
            s = fn(d, i)
            if s == 0: continue
            votes_by_bar.setdefault(i, []).append((name, s))
            if use_htf and not (m15[i] == s and h1[i] == s): continue
            r = simulate(m1, m1i, close_t[i], s, tp, sl)
            if r is None: continue
            trades.append((close_t[i], r[0])); busy_until = r[1] + 60
        res[name] = trades
    # combined: at least 2 strategies agree, none disagree (bot's non-fast mode)
    combo, busy_until = [], 0
    for i in sorted(votes_by_bar):
        v = votes_by_bar[i]; dirs = {s for _, s in v}
        if len(dirs) != 1 or len(v) < 2 or close_t[i] < busy_until: continue
        s = dirs.pop()
        if use_htf and not (m15[i] == s and h1[i] == s): continue
        r = simulate(m1, m1i, close_t[i], s, tp, sl)
        if r is None: continue
        combo.append((close_t[i], r[0])); busy_until = r[1] + 60
    res["2 AGREE"] = combo
    table = {}
    for name, trades in res.items():
        a = [p for t, p in trades if t < split_t]; b = [p for t, p in trades if t >= split_t]
        def st(x): return [len(x), round(100 * sum(1 for p in x if p > 0) / len(x)) if x else 0, round(sum(x), 1)]
        table[name] = st(a) + st(b)
    return table

if __name__ == "__main__":
    m1 = [b for b in fetch()]
    print("candles", len(m1), "from", datetime.fromtimestamp(m1[0][0], timezone.utc), "to", datetime.fromtimestamp(m1[-1][0], timezone.utc))
    split_t = m1[0][0] + (m1[-1][0] - m1[0][0]) * 2 // 3
    print("first part = first 2/3 of the period, check part = last 1/3. cost per trade $%.2f" % COST)
    out = {}
    for tf in (1, 5, 15):
        for tp, sl in ((3.0, 3.5), (5.0, 3.0), (6.0, 3.0)):
            for htf in (True, False):
                key = "m%d tp%.1f sl%.1f htf=%s" % (tf, tp, sl, htf)
                t0 = time.time(); tab = run(m1, tf, tp, sl, htf, split_t); out[key] = tab
                print("\n== %s  (%.0fs)\n%-10s %18s | %18s" % (key, time.time() - t0, "strategy", "first: n win% net$", "check: n win% net$"))
                for name, r in tab.items():
                    print("%-10s %5d %4d%% %7.1f | %5d %4d%% %7.1f" % (name, *r))
                sys.stdout.flush()
    json.dump(out, open("results.json", "w"), indent=1)
