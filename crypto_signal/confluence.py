"""Combines every strategy into one weighted confluence signal with ATR-based risk levels."""

from dataclasses import dataclass, field, replace

import numpy as np
import pandas as pd

from . import indicators as ind
from .strategies import FILTERS, TRIGGERS


@dataclass(frozen=True)
class Profile:
    # How much each filter's vote counts. Max possible score = sum of weights.
    weights: dict = field(default_factory=lambda: {
        "ema_trend": 2.0, "ema_slope": 1.0, "supertrend": 1.5,
        "macd_momentum": 1.0, "adx_strength": 1.0,
    })
    triggers: tuple = ("rsi_pullback", "bollinger_reentry", "donchian_breakout", "ema_pullback")
    min_score: float = 5.0          # out of 6.5 with default weights
    allow_short: bool = True
    sl_atr: float = 1.5             # stop distance in ATRs
    tp_atr: float = 3.0             # target distance in ATRs
    breakeven_atr: float = 0.0      # move stop to entry once price moves this far (0 = off)
    max_bars: int = 48              # time stop
    session_hours: tuple = ()       # UTC hours allowed for entries; empty = 24/7
    max_atr_pct: float = 0.95       # skip entries when volatility is in its top 5%
    fee: float = 0.0005             # round-trip cost as a fraction of price


PROFILES = {
    # Gold: trade London + New York only, where gold actually trends.
    "gold": Profile(session_hours=tuple(range(7, 20)), fee=0.0003),
    # Gold, tighter target + breakeven stop: higher win rate, smaller wins.
    "gold_high_winrate": Profile(session_hours=tuple(range(7, 20)), fee=0.0003,
                                 sl_atr=2.0, tp_atr=1.5, breakeven_atr=1.0, min_score=5.5),
    # Bitcoin trades 24/7 and is more volatile.
    "btc": Profile(sl_atr=2.0, tp_atr=4.0, fee=0.001),
    "btc_high_winrate": Profile(sl_atr=2.5, tp_atr=1.75, breakeven_atr=1.25, min_score=5.5, fee=0.001),
}


class ConfluenceEngine:
    def __init__(self, profile: Profile | str = "btc", **overrides):
        p = PROFILES[profile] if isinstance(profile, str) else profile
        self.profile = replace(p, **overrides) if overrides else p

    def votes(self, df: pd.DataFrame) -> pd.DataFrame:
        cols = {name: FILTERS[name](df) for name in self.profile.weights}
        cols.update({name: TRIGGERS[name](df) for name in self.profile.triggers})
        return pd.DataFrame(cols, index=df.index)

    def signals(self, df: pd.DataFrame) -> pd.DataFrame:
        """One row per bar: score, direction (+1/-1/0), and stop/target for that entry."""
        p = self.profile
        v = self.votes(df)
        w = pd.Series(p.weights)
        score = (v[list(w.index)] * w).sum(axis=1)
        trig = v[list(p.triggers)]
        long_trig = (trig == 1).any(axis=1)
        short_trig = (trig == -1).any(axis=1)

        a = ind.atr(df)
        atr_rank = (a / df["close"]).rolling(500, min_periods=100).rank(pct=True)
        ok = (atr_rank <= p.max_atr_pct).fillna(False)
        ok &= pd.Series(np.arange(len(df)) >= 200, index=df.index)   # indicator warm-up
        if p.session_hours:
            ok &= pd.Series(df.index.hour.isin(p.session_hours), index=df.index)

        direction = np.where(ok & long_trig & (score >= p.min_score), 1,
                    np.where(ok & short_trig & (score <= -p.min_score) & p.allow_short, -1, 0))
        out = pd.DataFrame({"score": score, "direction": direction, "atr": a,
                            "close": df["close"]}, index=df.index)
        out["stop"] = out["close"] - out["direction"] * p.sl_atr * a
        out["target"] = out["close"] + out["direction"] * p.tp_atr * a
        out["triggers"] = trig.apply(lambda r: ",".join(r.index[r != 0]), axis=1)
        return out

    def latest(self, df: pd.DataFrame) -> dict:
        s = self.signals(df).iloc[-1]
        side = {1: "BUY", -1: "SELL", 0: "NO TRADE"}[int(s["direction"])]
        res = {"time": str(df.index[-1]), "signal": side, "score": round(float(s["score"]), 2),
               "max_score": sum(self.profile.weights.values()), "price": float(s["close"]),
               "triggers": s["triggers"] or "-"}
        if s["direction"]:
            res.update(stop=round(float(s["stop"]), 2), target=round(float(s["target"]), 2))
        return res
