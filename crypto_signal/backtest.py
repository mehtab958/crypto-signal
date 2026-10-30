"""Bar-based backtester.

Convention (no look-ahead): a strategy's target position at bar t is computed from data up to
and including bar t's close, and is held over the return from close[t] to close[t+1]. This is
exactly what the live bot does: it waits for a candle to close, then trades.

Costs: every change in position pays `fee + slippage` on the traded notional.
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

BARS_PER_YEAR = {"1h": 24 * 365, "4h": 6 * 365, "1d": 365}


@dataclass
class Result:
    name: str
    equity: pd.Series
    position: pd.Series
    trades: pd.DataFrame
    stats: dict = field(default_factory=dict)


def extract_trades(close: pd.Series, pos: pd.Series, net_ret: pd.Series) -> pd.DataFrame:
    """A trade is a contiguous run of non-zero position (sign changes split trades)."""
    p = pos.to_numpy()
    sign = np.sign(p)
    rows = []
    start = None
    for i in range(len(p)):
        if start is None and sign[i] != 0:
            start = i
        elif start is not None and sign[i] != sign[start]:
            rows.append((start, i))
            start = i if sign[i] != 0 else None
    if start is not None:
        rows.append((start, len(p) - 1))
    out = []
    r = net_ret.to_numpy()
    for s, e in rows:
        # returns earned while held: bars s+1..e (position at s applies to return s->s+1);
        # include the exit cost charged at bar e.
        pnl = np.prod(1 + r[s + 1 : e + 1]) - 1 if e > s else 0.0
        out.append(
            {
                "entry_time": close.index[s],
                "exit_time": close.index[e],
                "side": "long" if sign[s] > 0 else "short",
                "entry_price": close.iloc[s],
                "exit_price": close.iloc[e],
                "bars": e - s,
                "return": pnl,
            }
        )
    return pd.DataFrame(out)


def run(
    df: pd.DataFrame,
    position: pd.Series,
    timeframe: str,
    name: str = "strategy",
    fee: float = 0.001,
    slippage: float = 0.0005,
    initial: float = 10_000.0,
) -> Result:
    pos = position.reindex(df.index).fillna(0.0).clip(-1, 1)
    ret = df["close"].pct_change().fillna(0.0)
    held = pos.shift(1).fillna(0.0)
    turnover = pos.diff().abs().fillna(pos.abs())
    net = held * ret - turnover * (fee + slippage)
    equity = initial * (1 + net).cumprod()
    trades = extract_trades(df["close"], pos, net)
    stats = compute_stats(equity, net, held, trades, BARS_PER_YEAR[timeframe])
    return Result(name, equity, pos, trades, stats)


def compute_stats(equity, net, held, trades, bpy) -> dict:
    years = len(equity) / bpy
    total = equity.iloc[-1] / equity.iloc[0] - 1
    cagr = (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1 if years > 0 else 0.0
    sd = net.std()
    sharpe = net.mean() / sd * np.sqrt(bpy) if sd > 0 else 0.0
    dsd = net[net < 0].std()
    sortino = net.mean() / dsd * np.sqrt(bpy) if dsd and dsd > 0 else 0.0
    dd = equity / equity.cummax() - 1
    mdd = dd.min()
    n = len(trades)
    wins = trades["return"][trades["return"] > 0] if n else pd.Series(dtype=float)
    losses = trades["return"][trades["return"] <= 0] if n else pd.Series(dtype=float)
    pf = wins.sum() / -losses.sum() if n and losses.sum() < 0 else np.inf if n else 0.0
    return {
        "total_return": total,
        "cagr": cagr,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": mdd,
        "calmar": cagr / -mdd if mdd < 0 else np.inf,
        "exposure": (held != 0).mean(),
        "trades": n,
        "trades_per_year": n / years if years > 0 else 0,
        "win_rate": len(wins) / n if n else 0.0,
        "profit_factor": pf,
        "avg_trade": trades["return"].mean() if n else 0.0,
    }


def buy_and_hold(df: pd.DataFrame, timeframe: str, **kw) -> Result:
    return run(df, pd.Series(1.0, index=df.index), timeframe, name="Buy & Hold", **kw)


def format_stats(rows: dict) -> pd.DataFrame:
    t = pd.DataFrame(rows).T
    pct = ["total_return", "cagr", "max_drawdown", "exposure", "win_rate", "avg_trade"]
    out = t.copy().astype(object)
    for c in t.columns:
        if c in pct:
            out[c] = t[c].map(lambda v: f"{v * 100:,.1f}%")
        elif c == "trades":
            out[c] = t[c].map(lambda v: f"{int(v)}")
        else:
            out[c] = t[c].map(lambda v: f"{v:,.2f}")
    return out
