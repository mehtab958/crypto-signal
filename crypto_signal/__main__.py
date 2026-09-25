"""CLI:
  python -m crypto_signal signal   --asset gold
  python -m crypto_signal backtest --asset btc --profile btc_high_winrate --bars 8000
  python -m crypto_signal backtest --csv xauusd_1h.csv --profile gold
  python -m crypto_signal basket   --asset gold --target 2 --stop 15
"""

import argparse

from .backtest import backtest
from .basket import BasketConfig, basket_backtest
from .confluence import PROFILES, ConfluenceEngine
from .data import fetch_binance, load_csv


def main():
    ap = argparse.ArgumentParser(prog="crypto_signal")
    ap.add_argument("command", choices=["signal", "backtest", "basket"])
    ap.add_argument("--asset", default="btc", help="btc | gold | any Binance symbol")
    ap.add_argument("--profile", help=f"one of {', '.join(PROFILES)} (default: the asset)")
    ap.add_argument("--csv", help="load candles from CSV instead of Binance")
    ap.add_argument("--interval", default="1h")
    ap.add_argument("--bars", type=int, default=5000)
    ap.add_argument("--trades", action="store_true", help="print the trade / basket log")
    b = BasketConfig()
    ap.add_argument("--balance", type=float, default=b.balance)
    ap.add_argument("--lot-value", type=float, default=b.value_per_point,
                    help="$ per $1 price move per trade (0.03 = 0.03 cent lot on gold)")
    ap.add_argument("--spread", type=float, default=b.spread)
    ap.add_argument("--max-trades", type=int, default=b.max_trades)
    ap.add_argument("--target", type=float, default=b.target, help="basket take-profit in $")
    ap.add_argument("--stop", type=float, default=b.stop, help="basket stop-loss in $")
    args = ap.parse_args()

    df = load_csv(args.csv) if args.csv else fetch_binance(args.asset, args.interval, args.bars)
    engine = ConfluenceEngine(args.profile or args.asset)

    if args.command == "signal":
        for k, v in engine.latest(df).items():
            print(f"{k:>10}: {v}")
        return

    if args.command == "basket":
        cfg = BasketConfig(args.balance, args.lot_value, args.spread, args.max_trades, args.target, args.stop)
        res = basket_backtest(df, engine, cfg)
        log = res.pop("basket_log")
    else:
        res = backtest(df, engine)
        log = res.pop("trade_log")
    print(f"Data: {df.index[0]} -> {df.index[-1]} ({len(df)} bars)")
    for k, v in res.items():
        print(f"{k:>16}: {v:.2%}" if "win_rate" in k else f"{k:>16}: {v:.4f}" if k == "cents_per_minute"
              else f"{k:>16}: {v:.2f}" if isinstance(v, float) else f"{k:>16}: {v}")
    if args.trades:
        print(log.to_string())


if __name__ == "__main__":
    main()
