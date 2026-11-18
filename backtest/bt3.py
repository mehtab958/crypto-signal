#!/usr/bin/env python3
"""Fresh-data check of the fast setups that held up in the first 45-day test.
A = the 45 days BEFORE the first test (never used to pick anything), B = the first test's 45 days."""
import sys, time
from datetime import datetime, timezone
import backtest as B
B.DAYS = 95
m1 = B.fetch()
t1 = m1[-1][0]; split = t1 - 45 * 86400
print("candles", len(m1), "A:", datetime.fromtimestamp(m1[0][0] + 5 * 86400, timezone.utc).date(), "to", datetime.fromtimestamp(split, timezone.utc).date(), " B: last 45 days")
m1 = [b for b in m1 if b[0] >= m1[0][0]]
for tf, tp, sl, htf in ((1, 5.0, 3.0, False), (1, 6.0, 3.0, False), (1, 4.0, 3.0, False), (1, 5.0, 3.0, True), (5, 5.0, 3.0, True), (5, 6.0, 3.0, True), (1, 3.0, 3.5, False)):
    tab = B.run(m1, tf, tp, sl, htf, split)
    print("\n== m%d tp%.1f sl%.1f htf=%s" % (tf, tp, sl, htf))
    print("%-10s %22s | %22s" % ("strategy", "A (fresh): n win% net$", "B (picked on): n win% net$"))
    for name in ("bb", "sweep", "stoch", "pinbar", "volclimax", "2 AGREE"):
        r = tab[name]; print("%-10s %5d %4d%% %8.1f    | %5d %4d%% %8.1f" % (name, *r))
    sys.stdout.flush()
