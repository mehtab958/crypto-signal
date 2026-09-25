"""Shows the win-rate vs. expectancy trade-off: shrinking the target relative to the
stop always raises the win rate, but it does not make a strategy more profitable.

  python -m crypto_signal.sweep --asset gold
"""

import argparse

from .backtest import backtest
from .confluence import ConfluenceEngine
from .data import fetch_binance


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asset", default="btc")
    ap.add_argument("--bars", type=int, default=10000)
    args = ap.parse_args()
    df = fetch_binance(args.asset, "1h", args.bars)
    print(f"{'stop':>5} {'target':>6} {'trades':>6} {'win%':>6} {'exp R':>6} {'PF':>5} {'maxDD R':>7}")
    for sl, tp in [(1.5, 3.0), (1.5, 1.5), (2.0, 1.0), (3.0, 0.75), (4.0, 0.5), (6.0, 0.4)]:
        r = backtest(df, ConfluenceEngine(args.asset, sl_atr=sl, tp_atr=tp, max_bars=200))
        print(f"{sl:>5} {tp:>6} {r['trades']:>6} {r['win_rate']:>6.1%} {r['expectancy_r']:>6.2f} "
              f"{r['profit_factor']:>5.2f} {r['max_drawdown_r']:>7.1f}")


if __name__ == "__main__":
    main()
