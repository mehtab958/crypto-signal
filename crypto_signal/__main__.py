"""CLI:
  python -m crypto_signal signal   --asset gold
  python -m crypto_signal backtest --asset btc --profile btc_high_winrate --bars 8000
  python -m crypto_signal backtest --csv xauusd_1h.csv --profile gold
"""

import argparse

from .backtest import backtest
from .confluence import PROFILES, ConfluenceEngine
from .data import fetch_binance, load_csv


def main():
    ap = argparse.ArgumentParser(prog="crypto_signal")
    ap.add_argument("command", choices=["signal", "backtest"])
    ap.add_argument("--asset", default="btc", help="btc | gold | any Binance symbol")
    ap.add_argument("--profile", help=f"one of {', '.join(PROFILES)} (default: the asset)")
    ap.add_argument("--csv", help="load candles from CSV instead of Binance")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--bars", type=int, default=5000)
    ap.add_argument("--trades", action="store_true", help="print the trade log")
    args = ap.parse_args()

    df = load_csv(args.csv) if args.csv else fetch_binance(args.asset, args.interval, args.bars)
    engine = ConfluenceEngine(args.profile or args.asset)

    if args.command == "signal":
        for k, v in engine.latest(df).items():
            print(f"{k:>10}: {v}")
        return

    res = backtest(df, engine)
    log = res.pop("trade_log")
    print(f"Data: {df.index[0]} -> {df.index[-1]} ({len(df)} bars)")
    for k, v in res.items():
        print(f"{k:>15}: {v:.2%}" if k == "win_rate" else f"{k:>15}: {v:.2f}" if isinstance(v, float) else f"{k:>15}: {v}")
    if args.trades:
        print(log.to_string())


if __name__ == "__main__":
    main()
