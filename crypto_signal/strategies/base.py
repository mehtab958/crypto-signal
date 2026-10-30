from abc import ABC, abstractmethod

import numpy as np
import pandas as pd


class Strategy(ABC):
    """A strategy maps OHLCV candles to a target position in [0, 1] (fraction of capital).

    `generate` must be causal: the value at bar t may only depend on bars <= t. The live bot
    calls `generate` on the latest closed candles and trades towards the last value.
    """

    name: str = "base"
    default_params: dict = {}
    # grid used by the optimizer / robustness checks
    param_grid: dict = {}
    warmup: int = 200

    def __init__(self, **params):
        unknown = set(params) - set(self.default_params)
        if unknown:
            raise ValueError(f"{self.name}: unknown params {unknown}")
        self.params = {**self.default_params, **params}

    @abstractmethod
    def generate(self, df: pd.DataFrame) -> pd.Series: ...

    def __repr__(self):
        return f"{self.name}({', '.join(f'{k}={v}' for k, v in self.params.items())})"


def stateful_long(
    close: np.ndarray,
    entry: np.ndarray,
    exit_: np.ndarray,
    stop_dist: np.ndarray,
    max_bars: int = 0,
) -> np.ndarray:
    """Long-only state machine with a trailing (chandelier) stop evaluated on closes.

    entry/exit_: boolean arrays. stop_dist: distance (in price) of the trailing stop below the
    highest close since entry; NaN disables the stop. max_bars > 0 enforces a time stop.
    """
    n = len(close)
    pos = np.zeros(n)
    in_pos = False
    peak = stop = 0.0
    held = 0
    for i in range(n):
        if in_pos:
            held += 1
            peak = max(peak, close[i])
            if not np.isnan(stop_dist[i]):
                stop = max(stop, peak - stop_dist[i])
            if exit_[i] or close[i] < stop or (max_bars and held >= max_bars):
                in_pos = False
        elif entry[i]:
            in_pos = True
            peak = close[i]
            stop = close[i] - stop_dist[i] if not np.isnan(stop_dist[i]) else 0.0
            held = 0
        pos[i] = 1.0 if in_pos else 0.0
    return pos
