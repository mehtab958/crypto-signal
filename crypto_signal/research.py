"""Strategy research: grid search on in-sample data, then test on unseen out-of-sample data.

    python -m crypto_signal.research                 # IS/OOS table + writes config/portfolio.json
    python -m crypto_signal.research --walk-forward  # also yearly re-selected walk-forward test

Parameters are picked by a *robust* score (the median Sharpe of a parameter set and its
neighbours in the grid) rather than the single best Sharpe, to avoid fitting noise. A strategy
joins the portfolio only if, in-sample, it beats buy & hold's Sharpe and at least 75% of its
parameter grid does too. Out-of-sample data is never used for any decision.
"""
import argparse
import itertools

import numpy as np
import pandas as pd

from . import backtest as bt
from . import portfolio as pf
from .data import load_csv
from .strategies import REGISTRY

TIMEFRAMES = ["4h", "1d"]
STATS_COLS = ["cagr", "sharpe", "max_drawdown", "calmar", "exposure", "trades", "win_rate",
              "profit_factor"]


def ts(s):
    return pd.Timestamp(s, tz="UTC")


def grid(param_grid: dict):
    """Yield (grid coordinates, params) for every combination."""
    keys = list(param_grid)
    for coords in itertools.product(*(range(len(param_grid[k])) for k in keys)):
        yield coords, {k: param_grid[k][i] for k, i in zip(keys, coords)}


def extra_params(name, timeframe):
    return {"bars_per_day": bt.BARS_PER_YEAR[timeframe] // 365} if name == "vol_momentum" else {}


def window(df, start, end=None):
    return df[(df.index >= start) & ((df.index < end) if end is not None else True)]


def score_grid(cls, df, timeframe, start, end, extra=None, min_trades=10):
    """Backtest every grid point on [start, end). Returns a DataFrame of params + stats."""
    rows = []
    w = window(df, start, end)
    for coords, params in grid(cls.param_grid):
        pos = cls(**params, **(extra or {})).generate(df)  # full history -> warmed-up indicators
        st = bt.run(w, pos, timeframe).stats
        if st["trades"] < min_trades:
            st["sharpe"] = -np.inf
        rows.append({"_coords": coords, "_params": params, **st})
    return pd.DataFrame(rows)


def robust_pick(res: pd.DataFrame) -> dict:
    """Pick the params whose neighbourhood (each param +/- one grid step) has the best median
    Sharpe. A lone spike surrounded by poor results is likely overfit and gets skipped."""
    coords = np.array(res["_coords"].tolist())
    sh = res["sharpe"].to_numpy()
    scores = [np.median(sh[np.all(np.abs(coords - c) <= 1, axis=1)]) for c in coords]
    return res["_params"].iloc[int(np.argmax(scores))]


def select_members(frames, start, end, verbose=False) -> list[pf.Member]:
    """Optimise every strategy x timeframe on [start, end) and keep the robust ones."""
    members = []
    for tf in TIMEFRAMES:
        df = frames[tf]
        bh = bt.buy_and_hold(window(df, start, end), tf).stats["sharpe"]
        for name, cls in REGISTRY.items():
            extra = extra_params(name, tf)
            res = score_grid(cls, df, tf, start, end, extra)
            params = robust_pick(res)
            strat = cls(**params, **extra)
            sharpe = bt.run(window(df, start, end), strat.generate(df), tf).stats["sharpe"]
            share = (res["sharpe"] > bh).mean()
            ok = share >= 0.75 and sharpe > bh
            if verbose:
                print(f"  {name + '@' + tf:22s} IS sharpe {sharpe:5.2f} (B&H {bh:4.2f}) | "
                      f"{share:6.1%} of grid beats B&H -> {'SELECTED' if ok else 'rejected'}")
            if ok:
                members.append(pf.Member(strat, tf))
    return members


def load_frames(base="4h"):
    return {tf: load_csv("BTCUSD", tf, start="2016-01-01") for tf in TIMEFRAMES}


def in_out_sample(start="2017-01-01", split="2023-01-01", out=None):
    frames = load_frames()
    start, split = ts(start), ts(split)
    print(f"Selecting on in-sample {start.date()} .. {split.date()}")
    members = select_members(frames, start, split, verbose=True)
    base = frames["4h"]
    per = pf.member_positions(members, frames, "4h")
    rows = {}
    for label, (a, b) in {"in-sample": (start, split), "out-of-sample": (split, None)}.items():
        w = window(base, a, b)
        rows[("Buy & Hold", label)] = bt.buy_and_hold(w, "4h").stats
        rows[("PORTFOLIO", label)] = bt.run(w, per.mean(axis=1), "4h").stats
        for k in per:
            rows[(k, label)] = bt.run(w, per[k], "4h").stats
    if out:
        pf.save(out, members, {"selected_on": [str(start.date()), str(split.date())],
                               "base_timeframe": "4h"})
        print(f"wrote {out}")
    return rows, members


def walk_forward(start="2017-01-01", first_test_year=2019):
    """Each year, re-select and re-optimise the portfolio on all data before that year
    (expanding window), then trade it for that year. Stitches the yearly out-of-sample results."""
    frames = load_frames()
    base = frames["4h"]
    pieces, year = [], first_test_year
    while ts(f"{year}-01-01") < base.index[-1]:
        members = select_members(frames, ts(start), ts(f"{year}-01-01"))
        pos = pf.combine(members, frames, "4h")
        pieces.append(window(pos, ts(f"{year}-01-01"), ts(f"{year + 1}-01-01")))
        print(f"  {year}: {len(members)} members: {', '.join(m.key for m in members)}")
        year += 1
    pos = pd.concat(pieces)
    w = window(base, pos.index[0])
    return bt.run(w, pos, "4h", name="walk-forward"), bt.buy_and_hold(w, "4h")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", default="2023-01-01")
    ap.add_argument("--out", default="config/portfolio.json")
    ap.add_argument("--walk-forward", action="store_true")
    a = ap.parse_args()
    pd.set_option("display.width", 200)
    rows, _ = in_out_sample(split=a.split, out=a.out)
    t = bt.format_stats(rows)[STATS_COLS]
    print(t.sort_index(level=1, sort_remaining=False).to_string())
    if a.walk_forward:
        print("Walk-forward (yearly re-selection, expanding window):")
        wf, bh = walk_forward()
        print(bt.format_stats({"walk-forward": wf.stats, "Buy & Hold": bh.stats})[STATS_COLS]
              .to_string())


if __name__ == "__main__":
    main()
