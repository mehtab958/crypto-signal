"""Individual strategies. Each one votes +1 (long), -1 (short) or 0 on every bar.

Strategies are split into two kinds:
  * filters  - describe the market *state* (trend, momentum). They are true for many bars.
  * triggers - describe an *event* (pullback ending, breakout, band re-entry). They fire rarely.

The confluence engine only opens a trade when a trigger fires AND the weighted
vote of everything agrees, which is what keeps the trade count low and quality high.
"""

import numpy as np
import pandas as pd

from . import indicators as ind


def _sign(long_cond, short_cond, index) -> pd.Series:
    return pd.Series(np.where(long_cond, 1, np.where(short_cond, -1, 0)), index=index)


# ---------------------------------------------------------------- filters

def ema_trend(df, fast=50, slow=200):
    """Classic trend regime: price and fast EMA on the same side of the slow EMA."""
    f, s = ind.ema(df["close"], fast), ind.ema(df["close"], slow)
    c = df["close"]
    return _sign((c > s) & (f > s), (c < s) & (f < s), df.index)


def ema_slope(df, n=200, lookback=20):
    """Higher-timeframe proxy: direction of the slow EMA over the last `lookback` bars."""
    e = ind.ema(df["close"], n)
    return _sign(e > e.shift(lookback), e < e.shift(lookback), df.index)


def supertrend(df, n=10, mult=3.0):
    return ind.supertrend(df, n, mult).astype(int)


def macd_momentum(df):
    _, _, hist = ind.macd(df["close"])
    return _sign((hist > 0) & (hist > hist.shift()), (hist < 0) & (hist < hist.shift()), df.index)


def adx_strength(df, n=14, level=20):
    """Votes with the dominant DI only when the trend is strong enough to trade."""
    a, plus_di, minus_di = ind.adx(df, n)
    strong = a > level
    return _sign(strong & (plus_di > minus_di), strong & (minus_di > plus_di), df.index)


# ---------------------------------------------------------------- triggers

def rsi_pullback(df, n=14, low=40, high=60, window=5):
    """RSI dips below `low` then recovers above it (buy the dip), mirrored for shorts."""
    r = ind.rsi(df["close"], n)
    dipped = (r < low).rolling(window).max().astype(bool)
    spiked = (r > high).rolling(window).max().astype(bool)
    return _sign(
        dipped.shift().fillna(False) & (r > low) & (r.shift() <= low),
        spiked.shift().fillna(False) & (r < high) & (r.shift() >= high),
        df.index,
    )


def bollinger_reentry(df, n=20, k=2.0):
    """Close back inside the band after closing outside it (failed extension)."""
    lo, _, hi = ind.bollinger(df["close"], n, k)
    c = df["close"]
    return _sign((c.shift() < lo.shift()) & (c > lo), (c.shift() > hi.shift()) & (c < hi), df.index)


def donchian_breakout(df, n=20):
    lo, hi = ind.donchian(df, n)
    c = df["close"]
    return _sign((c > hi) & (c.shift() <= hi.shift()), (c < lo) & (c.shift() >= lo.shift()), df.index)


def ema_pullback(df, fast=21, slow=50):
    """Price tags the fast EMA inside a trend and closes back in the trend direction."""
    f, s = ind.ema(df["close"], fast), ind.ema(df["close"], slow)
    up = (f > s) & (df["low"] <= f) & (df["close"] > f) & (df["close"] > df["open"])
    dn = (f < s) & (df["high"] >= f) & (df["close"] < f) & (df["close"] < df["open"])
    return _sign(up, dn, df.index)


FILTERS = {
    "ema_trend": ema_trend,
    "ema_slope": ema_slope,
    "supertrend": supertrend,
    "macd_momentum": macd_momentum,
    "adx_strength": adx_strength,
}

TRIGGERS = {
    "rsi_pullback": rsi_pullback,
    "bollinger_reentry": bollinger_reentry,
    "donchian_breakout": donchian_breakout,
    "ema_pullback": ema_pullback,
}
