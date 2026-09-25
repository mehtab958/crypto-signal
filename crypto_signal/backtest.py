"""Bar-by-bar backtester. Enters on the next bar's open (no look-ahead); if a bar
touches both stop and target, the stop is assumed to hit first (conservative)."""

import numpy as np
import pandas as pd

from .confluence import ConfluenceEngine


def backtest(df: pd.DataFrame, engine: ConfluenceEngine) -> dict:
    p = engine.profile
    sig = engine.signals(df)
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    d, a = sig["direction"].to_numpy(), sig["atr"].to_numpy()
    trades, i, n = [], 0, len(df)

    while i < n - 1:
        if d[i] == 0:
            i += 1
            continue
        side, j = d[i], i + 1
        entry = o[j]
        risk = p.sl_atr * a[i]
        stop, target = entry - side * risk, entry + side * p.tp_atr * a[i]
        exit_px, reason = None, "time"
        for k in range(j, min(j + p.max_bars, n)):
            hit_stop = l[k] <= stop if side > 0 else h[k] >= stop
            hit_tgt = h[k] >= target if side > 0 else l[k] <= target
            if hit_stop:
                exit_px, reason = stop, "stop"
                break
            if hit_tgt:
                exit_px, reason = target, "target"
                break
            if p.breakeven_atr and side * (c[k] - entry) >= p.breakeven_atr * a[i]:
                stop = entry if side > 0 and stop < entry or side < 0 and stop > entry else stop
        else:
            k = min(j + p.max_bars, n) - 1
            exit_px = c[k]
        r = (side * (exit_px - entry) - p.fee * entry) / risk
        trades.append({"entry_time": df.index[j], "exit_time": df.index[k], "side": int(side),
                       "entry": entry, "exit": exit_px, "reason": reason, "r": r})
        i = k + 1

    return summarize(pd.DataFrame(trades))


def summarize(t: pd.DataFrame) -> dict:
    if t.empty:
        return {"trades": 0, "win_rate": 0.0, "trade_log": t}
    wins, losses = t[t.r > 0], t[t.r <= 0]
    equity = t.r.cumsum()
    gross_loss = -losses.r.sum()
    return {
        "trades": len(t),
        "win_rate": len(wins) / len(t),
        "avg_win_r": wins.r.mean() if len(wins) else 0.0,
        "avg_loss_r": losses.r.mean() if len(losses) else 0.0,
        "expectancy_r": t.r.mean(),
        "profit_factor": wins.r.sum() / gross_loss if gross_loss > 0 else np.inf,
        "total_r": equity.iloc[-1],
        "max_drawdown_r": (equity.cummax().clip(lower=0) - equity).max(),
        "trade_log": t,
    }
