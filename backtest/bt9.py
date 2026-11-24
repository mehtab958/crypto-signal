#!/usr/bin/env python3
"""Fresh-week check: gold setups on the days AFTER the earlier tests ended (18 Nov 2026)."""
import time
from datetime import datetime, timezone
import backtest as B, bt2

CUT = int(datetime(2026, 11, 18, 18, 0, tzinfo=timezone.utc).timestamp())
B.DAYS = 40
m1 = B.fetch(); m1i = {b[0]: n for n, b in enumerate(m1)}
print("candles to", datetime.fromtimestamp(m1[-1][0], timezone.utc), "| fresh period starts", datetime.fromtimestamp(CUT, timezone.utc))
def st(tr):
    n = len(tr); w = sum(1 for x in tr if x[1] > 0)
    return "%3d trades %3d%% won net $%+7.2f" % (n, round(100 * w / n) if n else 0, sum(x[1] for x in tr))
macd = [x + ("macd",) for x in bt2.candidates(m1, "macd")]
vsa = [x + ("vsa",) for x in bt2.candidates(m1, "vsa")]
for name, cands, mx in (("MACD alone (m15, $6/$3)", macd, 1), ("VSA alone (m15, 1:2)", vsa, 1), ("Gold bot v30: MACD + VSA, 1 at a time", macd + vsa, 1)):
    tr = [x for x in bt2.portfolio(m1, m1i, cands, mx, {"vsa"}) if x[0] >= CUT]
    print("%-40s fresh week: %s" % (name, st(tr)))
tab = B.run(m1, 5, 6.0, 3.0, True, CUT)
r = tab["sweep"]
print("%-40s fresh week: %3d trades %3d%% won net $%+7.2f" % ("GoldSweep (m5 sweep, $6/$3, trend)", r[3], r[4], r[5]))
