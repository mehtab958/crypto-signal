"""Turns OHLCV candles into a scored trading signal."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from . import indicators as ta


@dataclass
class Candle:
    open_time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class Signal:
    symbol: str
    interval: str
    price: float
    verdict: str  # STRONG BUY | BUY | NEUTRAL | SELL | STRONG SELL
    score: int
    rsi: float
    ema20: float
    ema50: float
    ema200: float | None
    macd_hist: float
    bb_lower: float
    bb_upper: float
    atr: float
    support: float
    resistance: float
    stop_loss: float | None
    take_profit: float | None
    change_pct: float
    volume_ratio: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {k: (_round(v) if isinstance(v, float) else v) for k, v in asdict(self).items()}


def _round(x: float) -> float | None:
    if x is None or math.isnan(x):
        return None
    if abs(x) >= 100:
        return round(x, 2)
    if abs(x) >= 1:
        return round(x, 4)
    return float(f"{x:.6g}")


MIN_CANDLES = 60


def analyze(symbol: str, interval: str, candles: list[Candle]) -> Signal:
    if len(candles) < MIN_CANDLES:
        raise ValueError(f"need at least {MIN_CANDLES} candles, got {len(candles)}")

    closes = [c.close for c in candles]
    highs = [c.high for c in candles]
    lows = [c.low for c in candles]
    volumes = [c.volume for c in candles]
    price = closes[-1]

    rsi = ta.rsi(closes)[-1]
    ema20 = ta.ema(closes, 20)[-1]
    ema50 = ta.ema(closes, 50)[-1]
    ema200_series = ta.ema(closes, 200)
    ema200 = ema200_series[-1] if not math.isnan(ema200_series[-1]) else None
    _, _, hist = ta.macd(closes)
    macd_hist, macd_prev = hist[-1], hist[-2]
    bb_lower, _, bb_upper = (band[-1] for band in ta.bollinger(closes))
    atr = ta.atr(highs, lows, closes)[-1]

    lookback = candles[-50:]
    support = min(c.low for c in lookback)
    resistance = max(c.high for c in lookback)

    change_pct = (price / closes[-25] - 1) * 100 if len(closes) > 25 else math.nan
    avg_vol = sum(volumes[-21:-1]) / 20
    volume_ratio = volumes[-1] / avg_vol if avg_vol else math.nan

    score = 0
    reasons: list[str] = []

    if rsi < 30:
        score += 2
        reasons.append(f"RSI {rsi:.0f}: oversold")
    elif rsi < 40:
        score += 1
        reasons.append(f"RSI {rsi:.0f}: leaning oversold")
    elif rsi > 70:
        score -= 2
        reasons.append(f"RSI {rsi:.0f}: overbought")
    elif rsi > 60:
        score -= 1
        reasons.append(f"RSI {rsi:.0f}: leaning overbought")
    else:
        reasons.append(f"RSI {rsi:.0f}: neutral")

    if ema20 > ema50:
        score += 1
        reasons.append("EMA20 above EMA50: short-term uptrend")
    else:
        score -= 1
        reasons.append("EMA20 below EMA50: short-term downtrend")

    if ema200 is not None:
        if price > ema200:
            score += 1
            reasons.append("price above EMA200: long-term bullish")
        else:
            score -= 1
            reasons.append("price below EMA200: long-term bearish")

    if macd_hist > 0 and macd_hist > macd_prev:
        score += 1
        reasons.append("MACD histogram positive and rising")
    elif macd_hist < 0 and macd_hist < macd_prev:
        score -= 1
        reasons.append("MACD histogram negative and falling")
    else:
        reasons.append("MACD momentum fading")

    if price < bb_lower:
        score += 1
        reasons.append("price below lower Bollinger band")
    elif price > bb_upper:
        score -= 1
        reasons.append("price above upper Bollinger band")

    if score >= 3:
        verdict = "STRONG BUY"
    elif score >= 1:
        verdict = "BUY"
    elif score <= -3:
        verdict = "STRONG SELL"
    elif score <= -1:
        verdict = "SELL"
    else:
        verdict = "NEUTRAL"

    stop_loss = take_profit = None
    if not math.isnan(atr):
        if score > 0:
            stop_loss, take_profit = price - 1.5 * atr, price + 3 * atr
        elif score < 0:
            stop_loss, take_profit = price + 1.5 * atr, price - 3 * atr

    return Signal(
        symbol=symbol,
        interval=interval,
        price=price,
        verdict=verdict,
        score=score,
        rsi=rsi,
        ema20=ema20,
        ema50=ema50,
        ema200=ema200,
        macd_hist=macd_hist,
        bb_lower=bb_lower,
        bb_upper=bb_upper,
        atr=atr,
        support=support,
        resistance=resistance,
        stop_loss=stop_loss,
        take_profit=take_profit,
        change_pct=change_pct,
        volume_ratio=volume_ratio,
        reasons=reasons,
    )
