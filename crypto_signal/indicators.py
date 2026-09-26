"""Pure technical-analysis helpers. Inputs are oldest-first lists of floats."""

from __future__ import annotations

import math


def sma(values: list[float], period: int) -> list[float]:
    out = [math.nan] * len(values)
    if period <= 0 or len(values) < period:
        return out
    window = sum(values[:period])
    out[period - 1] = window / period
    for i in range(period, len(values)):
        window += values[i] - values[i - period]
        out[i] = window / period
    return out


def ema(values: list[float], period: int) -> list[float]:
    """EMA seeded with the SMA of the first `period` values."""
    out = [math.nan] * len(values)
    if period <= 0 or len(values) < period:
        return out
    k = 2 / (period + 1)
    prev = sum(values[:period]) / period
    out[period - 1] = prev
    for i in range(period, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def rsi(closes: list[float], period: int = 14) -> list[float]:
    """Wilder's RSI."""
    out = [math.nan] * len(closes)
    if len(closes) <= period:
        return out
    gains = losses = 0.0
    for i in range(1, period + 1):
        change = closes[i] - closes[i - 1]
        gains += max(change, 0.0)
        losses += max(-change, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for i in range(period + 1, len(closes)):
        change = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(change, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-change, 0.0)) / period
        out[i] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100 - 100 / (1 + rs)


def macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float], list[float], list[float]]:
    """Returns (macd_line, signal_line, histogram)."""
    fast_ema, slow_ema = ema(closes, fast), ema(closes, slow)
    line = [f - s for f, s in zip(fast_ema, slow_ema)]
    start = slow - 1
    signal_tail = ema(line[start:], signal) if len(line) > start else []
    signal_line = [math.nan] * start + signal_tail
    hist = [m - s for m, s in zip(line, signal_line)]
    return line, signal_line, hist


def bollinger(
    closes: list[float], period: int = 20, mult: float = 2.0
) -> tuple[list[float], list[float], list[float]]:
    """Returns (lower, middle, upper) bands."""
    mid = sma(closes, period)
    lower = [math.nan] * len(closes)
    upper = [math.nan] * len(closes)
    for i in range(period - 1, len(closes)):
        window = closes[i - period + 1 : i + 1]
        mean = mid[i]
        std = math.sqrt(sum((x - mean) ** 2 for x in window) / period)
        lower[i], upper[i] = mean - mult * std, mean + mult * std
    return lower, mid, upper


def atr(highs: list[float], lows: list[float], closes: list[float], period: int = 14) -> list[float]:
    """Wilder's Average True Range."""
    n = len(closes)
    out = [math.nan] * n
    if n <= period:
        return out
    trs = [highs[0] - lows[0]]
    for i in range(1, n):
        trs.append(
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        )
    prev = sum(trs[1 : period + 1]) / period
    out[period] = prev
    for i in range(period + 1, n):
        prev = (prev * (period - 1) + trs[i]) / period
        out[i] = prev
    return out
