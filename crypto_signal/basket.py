"""Basket-close mode: open a trade on every confluence signal (up to `max_trades` at once),
with no per-trade stop. Close the whole basket when its combined profit reaches `target`
or its combined loss reaches `stop`. Money is in account dollars.

The basket stop is not optional: without it, one move against the basket never comes
back to profit and the account is eventually wiped out (see README).
Checks run on bar closes, so live fills will be somewhat worse than this.
"""

from dataclasses import dataclass

import pandas as pd

from .confluence import ConfluenceEngine


@dataclass(frozen=True)
class BasketConfig:
    balance: float = 100.0
    value_per_point: float = 0.03   # $ gained per $1 price move, per trade (0.03 cent lot on gold)
    spread: float = 0.30            # entry cost per trade, in price units
    max_trades: int = 5
    target: float = 2.0             # close all when basket profit >= this ($)
    stop: float = 15.0              # close all when basket loss >= this ($)


def floating(positions, price, cfg: BasketConfig) -> float:
    return sum(side * (price - entry) - cfg.spread for side, entry in positions) * cfg.value_per_point


def basket_backtest(df: pd.DataFrame, engine: ConfluenceEngine, cfg: BasketConfig = BasketConfig()) -> dict:
    direction = engine.signals(df)["direction"].to_numpy()
    o, c = df["open"].to_numpy(), df["close"].to_numpy()
    bal, positions, opened_at, log = cfg.balance, [], None, []
    worst, blown_at = cfg.balance, None

    for i in range(len(df) - 1):
        fl = floating(positions, c[i], cfg)
        worst = min(worst, bal + fl)
        if bal + fl <= 0:
            bal, blown_at = 0.0, df.index[i]
            break
        if positions and (fl >= cfg.target or fl <= -cfg.stop):
            bal += fl
            log.append({"opened": opened_at, "closed": df.index[i], "trades": len(positions), "pnl": fl})
            positions = []
        if direction[i] and len(positions) < cfg.max_trades:
            if not positions:
                opened_at = df.index[i + 1]
            positions.append((direction[i], o[i + 1]))

    log = pd.DataFrame(log, columns=["opened", "closed", "trades", "pnl"])
    equity = bal + (floating(positions, c[-1], cfg) if blown_at is None else 0.0)
    minutes = (df.index[-1] - df.index[0]).total_seconds() / 60
    wins = (log.pnl > 0).sum()
    return {
        "start_balance": cfg.balance,
        "end_equity": equity,
        "baskets": len(log),
        "basket_win_rate": wins / len(log) if len(log) else 0.0,
        "worst_equity": worst,
        "blown_at": blown_at,
        "still_open": len(positions),
        "cents_per_minute": (equity - cfg.balance) * 100 / minutes,
        "basket_log": log,
    }
