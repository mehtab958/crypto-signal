"""Strategy library. Every strategy is long-only (spot friendly) and position-sized in [0, 1]."""
import numpy as np
import pandas as pd

from .. import indicators as ta
from .base import Strategy, stateful_long


class EmaTrend(Strategy):
    """Trend following: fast EMA above slow EMA with ADX confirming a trend.
    Exits on the opposite cross or an ATR chandelier stop."""

    name = "ema_trend"
    default_params = {"fast": 20, "slow": 100, "adx_min": 20, "atr_mult": 4.0}
    param_grid = {"fast": [10, 20, 30], "slow": [50, 100, 150, 200], "adx_min": [0, 15, 20, 25],
                  "atr_mult": [3.0, 4.0, 5.0]}

    def generate(self, df):
        p = self.params
        f, s = ta.ema(df["close"], p["fast"]), ta.ema(df["close"], p["slow"])
        a = ta.adx(df)
        entry = ((f > s) & (a > p["adx_min"])).to_numpy()
        exit_ = (f < s).to_numpy()
        stop = (ta.atr(df) * p["atr_mult"]).to_numpy()
        return pd.Series(stateful_long(df["close"].to_numpy(), entry, exit_, stop), df.index)


class DonchianBreakout(Strategy):
    """Channel breakout: buy a close above the N-bar high, exit below the M-bar low
    or on an ATR trailing stop."""

    name = "donchian_breakout"
    default_params = {"entry": 55, "exit": 20, "atr_mult": 4.0}
    param_grid = {"entry": [20, 40, 55, 80, 120], "exit": [10, 20, 30, 50], "atr_mult": [3.0, 4.0, 6.0]}

    def generate(self, df):
        p = self.params
        _, upper = ta.donchian(df, p["entry"])
        lower, _ = ta.donchian(df, p["exit"])
        entry = (df["close"] > upper).to_numpy()
        exit_ = (df["close"] < lower).to_numpy()
        stop = (ta.atr(df) * p["atr_mult"]).to_numpy()
        return pd.Series(stateful_long(df["close"].to_numpy(), entry, exit_, stop), df.index)


class RsiDipBuyer(Strategy):
    """Mean reversion inside an uptrend: buy short-term oversold dips (RSI) while price is above
    the long-term trend, sell into the bounce (close above short SMA) or after a time stop."""

    name = "rsi_dip"
    default_params = {"rsi_len": 3, "rsi_buy": 15, "trend": 200, "exit_sma": 5, "max_bars": 20,
                      "atr_mult": 3.0}
    param_grid = {"rsi_len": [2, 3, 4], "rsi_buy": [10, 15, 20, 25], "trend": [200, 600, 1200],
                  "exit_sma": [5, 10], "max_bars": [10, 20, 40], "atr_mult": [3.0]}

    def generate(self, df):
        p = self.params
        c = df["close"]
        r = ta.rsi(c, p["rsi_len"])
        entry = ((c > ta.sma(c, p["trend"])) & (r < p["rsi_buy"])).to_numpy()
        exit_ = (c > ta.sma(c, p["exit_sma"])).to_numpy()
        stop = (ta.atr(df) * p["atr_mult"]).to_numpy()
        return pd.Series(stateful_long(c.to_numpy(), entry, exit_, stop, p["max_bars"]), df.index)


class BollingerSqueeze(Strategy):
    """Volatility contraction -> expansion: when band width was recently in its lowest
    percentile and price closes above the upper band, go long. Exit below the middle band."""

    name = "bb_squeeze"
    default_params = {"length": 20, "k": 2.0, "lookback": 120, "pct": 0.25, "atr_mult": 3.0}
    param_grid = {"length": [20, 30], "k": [1.5, 2.0], "lookback": [60, 120, 240],
                  "pct": [0.1, 0.25, 0.4], "atr_mult": [3.0, 5.0]}

    def generate(self, df):
        p = self.params
        c = df["close"]
        lo, mid, up = ta.bollinger(c, p["length"], p["k"])
        width = (up - lo) / mid
        rank = width.rolling(p["lookback"]).rank(pct=True)
        squeezed = (rank < p["pct"]).rolling(p["length"]).max().astype(bool)
        entry = (squeezed & (c > up)).to_numpy()
        exit_ = (c < mid).to_numpy()
        stop = (ta.atr(df) * p["atr_mult"]).to_numpy()
        return pd.Series(stateful_long(c.to_numpy(), entry, exit_, stop), df.index)


class VolTargetMomentum(Strategy):
    """Time-series momentum over several horizons, sized by volatility targeting.

    signal = share of lookbacks (in days) with positive return (0..1);
    size = signal * target_vol / realized_vol, capped at 1. Rebalances only when the target moves
    by more than `band` to save fees."""

    name = "vol_momentum"
    default_params = {"lookbacks": (20, 60, 120), "target_vol": 0.5, "vol_days": 30, "band": 0.2,
                      "bars_per_day": 6}
    param_grid = {"lookbacks": [(10, 30, 60), (20, 60, 120), (30, 90, 180), (60, 120, 240)],
                  "target_vol": [0.4, 0.6, 0.8], "vol_days": [15, 30, 60], "band": [0.1, 0.25]}

    def generate(self, df):
        p = self.params
        c = df["close"]
        bpd = p["bars_per_day"]
        sig = sum((c > c.shift(n * bpd)).astype(float) for n in p["lookbacks"]) / len(p["lookbacks"])
        vol = ta.realized_vol(c, p["vol_days"] * bpd, 365 * bpd)
        raw = (sig * p["target_vol"] / vol).clip(0, 1).fillna(0.0).to_numpy()
        return pd.Series(_banded(raw, p["band"]), df.index)


def _banded(target: np.ndarray, band: float) -> np.ndarray:
    """Only move to a new target when it differs from the current holding by more than band
    (or goes to/from zero)."""
    out = np.empty_like(target)
    cur = 0.0
    for i, t in enumerate(target):
        if abs(t - cur) > band or (t == 0) != (cur == 0):
            cur = t
        out[i] = cur
    return out


REGISTRY = {cls.name: cls for cls in
            [EmaTrend, DonchianBreakout, RsiDipBuyer, BollingerSqueeze, VolTargetMomentum]}
