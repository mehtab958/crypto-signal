#!/usr/bin/env python3
"""1) What Deriv offers for rise/fall on gold and forex: durations and payout.
2) Fresh-data check of the best binary setups (gold, PAXG prices) on the 60 days BEFORE the first test."""
import asyncio, json, time
import websockets
import backtest as B

URL = "wss://api.derivws.com/trading/v1/options/ws/public"

async def deriv():
    async with websockets.connect(URL, open_timeout=20, max_size=2 ** 24) as ws:
        async def ask(req):
            await ws.send(json.dumps(req)); return json.loads(await asyncio.wait_for(ws.recv(), 30))
        for sym in ("frxXAUUSD", "frxEURUSD", "frxGBPUSD"):
            r = await ask({"contracts_for": sym, "currency": "USD", "landing_company": "svg"})
            if r.get("error"):
                print(sym, "contracts_for error:", r["error"].get("message")); continue
            seen = set()
            for c in r["contracts_for"]["available"]:
                if c.get("contract_type") in ("CALL", "PUT") and c.get("contract_category") == "callput":
                    key = (c.get("barrier_category"), c.get("expiry_type"), c.get("min_contract_duration"), c.get("max_contract_duration"), c.get("start_type"))
                    if key not in seen:
                        seen.add(key); print(sym, "rise/fall:", key)
            for dur, unit in ((1, "m"), (5, "m"), (15, "m"), (1, "h"), (1, "d")):
                p = await ask({"proposal": 1, "amount": 10, "basis": "stake", "contract_type": "CALL", "currency": "USD",
                               "duration": dur, "duration_unit": unit, "underlying_symbol": sym, "symbol": sym})
                if p.get("error"):
                    p = await ask({"proposal": 1, "amount": 10, "basis": "stake", "contract_type": "CALL", "currency": "USD",
                                   "duration": dur, "duration_unit": unit, "symbol": sym})
                if p.get("error"):
                    print("  %s %d%s: %s" % (sym, dur, unit, p["error"].get("message")))
                else:
                    pay = float(p["proposal"]["payout"]); print("  %s %d%s: $10 stake pays $%.2f -> profit %.0f%%, break-even win rate %.1f%%" % (sym, dur, unit, pay, (pay - 10) * 10, 1000 / pay))

def fetch_range(symbol, start_days_ago, end_days_ago):
    now = int(time.time() // 60 * 60 * 1000); t = now - start_days_ago * 86400 * 1000; end = now - end_days_ago * 86400 * 1000; out = []
    while t < end:
        rows = B.get("https://data-api.binance.vision/api/v3/klines?symbol=%s&interval=1m&limit=1000&startTime=%d&endTime=%d" % (symbol, t, end))
        if not rows: break
        out += [(int(k[0]) // 1000, float(k[1]), float(k[2]), float(k[3]), float(k[4]), float(k[5])) for k in rows]
        t = rows[-1][0] + 60000
    return out

def binary(m1, tf, expiry, name, htf):
    fn = dict(B.STRATS)[name]; idx = {b[0]: n for n, b in enumerate(m1)}
    bars = m1 if tf == 1 else B.agg(m1, tf); d = B.Ind(bars); ct = [b[0] + tf * 60 for b in bars]
    m15 = B.htf_trend(B.agg(m1, 15), ct); h1 = B.htf_trend(B.agg(m1, 60), ct)
    n = w = busy = 0
    for i in range(110, len(bars) - 1):
        if ct[i] < busy or not B.gold_open(ct[i]): continue
        s = fn(d, i)
        if s == 0 or (htf and not (m15[i] == s and h1[i] == s)): continue
        k = idx.get(ct[i])
        if k is None or k + expiry >= len(m1): continue
        a, b = m1[k][1], m1[k + expiry][1]; busy = ct[i] + expiry * 60
        if a == b: continue
        n += 1; w += (b - a) * s > 0
    return n, w

try:
    asyncio.run(deriv())
except Exception as e:
    print("Deriv query failed:", e)

print("\nFresh gold data: 60 to 125 days ago (the earlier binary test used the last 60 days)")
m1 = fetch_range("PAXGUSDT", 125, 60)
print("candles", len(m1))
for name, tf, exp, htf, before in (("macd", 5, 15, True, "57.8% / 56.2%"), ("fvg", 1, 1, True, "54.6% / 54.4%"), ("fvg", 1, 3, True, "54.1% / 54.5%"),
                                    ("fvg", 15, 15, True, "54.2% / 56.4%"), ("stoch", 5, 15, True, "58.5% / 53.5%"), ("fvg", 15, 15, False, "56.0% / 54.0%")):
    n, w = binary(m1, tf, exp, name, htf)
    print("  %-6s signal m%-2d expiry %2d min trend=%-5s  earlier test %-14s -> fresh data: %4d trades %5.1f%% won" % (name, tf, exp, htf, before, n, 100.0 * w / n if n else 0))
