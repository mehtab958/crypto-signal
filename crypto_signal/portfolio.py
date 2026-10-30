"""A portfolio is a weighted blend of (strategy, timeframe) members.

Each member produces a target position on its own timeframe. Positions are aligned on the
*close time* of their candles (a daily signal only becomes known when the daily candle closes)
and forward-filled onto the base timeframe, then averaged by weight.
"""
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .strategies import REGISTRY, Strategy

TF_DELTA = {"1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4), "1d": pd.Timedelta(days=1)}


def norm_tf(tf: str) -> str:
    return "1d" if tf in ("1D", "1d") else tf


@dataclass
class Member:
    strategy: Strategy
    timeframe: str
    weight: float = 1.0

    @property
    def key(self):
        return f"{self.strategy.name}@{self.timeframe}"


def load(path) -> tuple[dict, list[Member]]:
    cfg = json.loads(Path(path).read_text())
    members = []
    for m in cfg["members"]:
        params = {k: tuple(v) if isinstance(v, list) else v for k, v in m.get("params", {}).items()}
        members.append(Member(REGISTRY[m["strategy"]](**params), norm_tf(m["timeframe"]),
                              m.get("weight", 1.0)))
    return cfg, members


def save(path, members: list[Member], meta: dict | None = None):
    out = {**(meta or {}), "members": [
        {"strategy": m.strategy.name, "timeframe": m.timeframe, "weight": m.weight,
         "params": {k: list(v) if isinstance(v, tuple) else v
                    for k, v in m.strategy.params.items()}}
        for m in members]}
    Path(path).write_text(json.dumps(out, indent=2) + "\n")


def member_positions(members: list[Member], frames: dict, base_tf: str) -> pd.DataFrame:
    """Per-member target positions on the base timeframe's index. `frames` maps timeframe ->
    OHLCV DataFrame indexed by candle open time."""
    base = frames[base_tf]
    cols = {}
    for m in members:
        pos = m.strategy.generate(frames[m.timeframe])
        # shift to "known at" time expressed as a base-timeframe open-time label
        pos.index = pos.index + TF_DELTA[m.timeframe] - TF_DELTA[base_tf]
        cols[m.key] = pos.reindex(base.index, method="ffill").fillna(0.0)
    return pd.DataFrame(cols, index=base.index)


def combine(members: list[Member], frames: dict, base_tf: str) -> pd.Series:
    pos = member_positions(members, frames, base_tf)
    w = pd.Series({m.key: m.weight for m in members})
    return (pos * w).sum(axis=1) / w.sum()
