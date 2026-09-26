import math

from crypto_signal import indicators as ta


def test_sma_and_ema_basic():
    vals = [1, 2, 3, 4, 5]
    assert ta.sma(vals, 3)[2:] == [2, 3, 4]
    e = ta.ema(vals, 3)
    assert math.isnan(e[1]) and e[2] == 2
    assert e[3] == 3 and e[4] == 4  # EMA of a straight line tracks it exactly after seeding


def test_rsi_extremes():
    up = [float(i) for i in range(30)]
    down = list(reversed(up))
    assert ta.rsi(up)[-1] == 100.0
    assert ta.rsi(down)[-1] == 0.0
    flat = [5.0] * 30
    assert ta.rsi(flat)[-1] == 50.0


def test_rsi_known_value():
    # Classic Wilder example data; first RSI value is ~70.53
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
              45.89, 46.03, 45.61, 46.28, 46.28]
    assert abs(ta.rsi(closes)[14] - 70.53) < 0.1


def test_macd_histogram_sign():
    rising = [100 * 1.01 ** i for i in range(80)]
    line, _, hist = ta.macd(rising)
    assert line[-1] > 0 and hist[-1] > 0  # accelerating uptrend
    falling = [100 * 0.99 ** i for i in range(80)]
    line, _, _ = ta.macd(falling)
    assert line[-1] < 0
    # Flat, then an abrupt drop: bearish momentum -> negative histogram
    drop = [100.0] * 60 + [100 - 2 * i for i in range(1, 15)]
    _, _, hist = ta.macd(drop)
    assert hist[-1] < 0


def test_bollinger_contains_mean():
    closes = [10, 11, 9, 10, 12, 8, 10, 11, 9, 10] * 3
    lower, mid, upper = ta.bollinger(closes, 20)
    assert lower[-1] < mid[-1] < upper[-1]


def test_atr_constant_range():
    n = 30
    highs, lows, closes = [11.0] * n, [9.0] * n, [10.0] * n
    assert abs(ta.atr(highs, lows, closes)[-1] - 2.0) < 1e-9
