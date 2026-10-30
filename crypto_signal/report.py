"""Generate results/RESULTS.md and charts for the configured portfolio.

    python -m crypto_signal.report [--config config/portfolio.json] [--walk-forward]
"""
import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from . import backtest as bt  # noqa: E402
from . import portfolio as pf  # noqa: E402
from .research import STATS_COLS, load_frames, ts, walk_forward, window  # noqa: E402

OUT = Path("results")


def md(df: pd.DataFrame) -> str:
    df = df.reset_index()
    df.columns = [" / ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in df.columns]
    lines = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(str(v) for v in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def yearly(equity: pd.Series) -> pd.Series:
    e = equity.resample("YE").last()
    first = equity.iloc[0]
    return e.pct_change().fillna(e.iloc[0] / first - 1)


def plot(results: dict, path: Path, title: str):
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True,
                                   gridspec_kw={"height_ratios": [3, 1]})
    for name, r in results.items():
        ax1.plot(r.equity.index, r.equity, label=name, lw=1.2)
        ax2.plot(r.equity.index, (r.equity / r.equity.cummax() - 1) * 100, lw=1)
    ax1.set_yscale("log")
    ax1.set_ylabel("equity (log, start $10k)")
    ax1.legend()
    ax1.set_title(title)
    ax2.set_ylabel("drawdown %")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config/portfolio.json")
    ap.add_argument("--walk-forward", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    cfg, members = pf.load(a.config)
    start, split = (ts(s) for s in cfg["selected_on"])
    frames = load_frames()
    base = frames["4h"]
    per = pf.member_positions(members, frames, "4h")
    port = per.mean(axis=1)
    doc = ["# Backtest results", "",
           "Data: Bitstamp BTC/USD, 1-minute candles resampled to 4h / 1d. Costs: 0.10% fee + "
           "0.05% slippage per side. Long-only, no leverage. Signals are computed on closed "
           "candles and applied from the next bar.", "",
           f"Strategies and parameters were chosen **only** on {start.date()} .. {split.date()}. "
           f"Everything from {split.date()} on is out-of-sample (never seen during selection).",
           ""]

    rows, curves = {}, {}
    for label, (s, e) in {"in-sample": (start, split), "out-of-sample": (split, None),
                          "full": (start, None)}.items():
        w = window(base, s, e)
        rows[("Buy & Hold", label)] = (bh := bt.buy_and_hold(w, "4h")).stats
        rows[("PORTFOLIO", label)] = (p := bt.run(w, port, "4h", name="Portfolio")).stats
        for k in per:
            rows[(k, label)] = bt.run(w, per[k], "4h").stats
        curves[label] = {"Buy & Hold": bh, "Portfolio": p}
    table = bt.format_stats(rows)[STATS_COLS].sort_index(level=1, sort_remaining=False)
    for label in ["out-of-sample", "in-sample", "full"]:
        doc += [f"## {label}", "", md(table.xs(label, level=1)), ""]
        plot(curves[label], OUT / f"equity_{label}.png", f"Portfolio vs Buy & Hold ({label})")
        doc += [f"![{label}](equity_{label}.png)", ""]

    yr = pd.DataFrame({"Portfolio": yearly(curves["full"]["Portfolio"].equity),
                       "Buy & Hold": yearly(curves["full"]["Buy & Hold"].equity)})
    yr.index = yr.index.year
    doc += ["## Calendar-year returns", "",
            md(yr.map(lambda v: f"{v * 100:,.1f}%")), ""]

    fee_rows = {}
    for fee in [0.0005, 0.001, 0.002]:
        r = bt.run(window(base, split), port, "4h", fee=fee)
        fee_rows[f"fee {fee * 100:.2f}% + 0.05% slip"] = r.stats
    doc += ["## Fee sensitivity (out-of-sample)", "",
            md(bt.format_stats(fee_rows)[["cagr", "sharpe", "max_drawdown"]]), ""]

    if a.walk_forward:
        wf, bh = walk_forward()
        doc += ["## Walk-forward (most realistic estimate)", "",
                "Every January the whole selection + optimisation is re-run on all prior data "
                "(from 2017) and the resulting portfolio is traded, unseen, for that year.", "",
                md(bt.format_stats({"walk-forward": wf.stats, "Buy & Hold": bh.stats})[STATS_COLS]),
                "", "![walk-forward](equity_walk_forward.png)", ""]
        plot({"Buy & Hold": bh, "Walk-forward portfolio": wf}, OUT / "equity_walk_forward.png",
             "Walk-forward portfolio vs Buy & Hold")

    doc += ["## Portfolio members", "", "| member | params |", "|---|---|"]
    doc += [f"| {m.key} | `{m.strategy.params}` |" for m in members]
    (OUT / "RESULTS.md").write_text("\n".join(doc) + "\n")
    print((OUT / "RESULTS.md").read_text())


if __name__ == "__main__":
    main()
