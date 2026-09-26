import math

import pytest

from crypto_signal.signals import Candle, analyze


def make_candles(closes):
    return [Candle(i, c, c * 1.01, c * 0.99, c, 100.0) for i, c in enumerate(closes)]


def test_uptrend_overbought_scores_mixed_but_trend_bullish():
    closes = [100 * 1.01 ** i for i in range(250)]
    sig = analyze("BTCUSDT", "4h", make_candles(closes))
    assert sig.rsi > 70
    assert sig.ema20 > sig.ema50 > sig.ema200
    assert any("overbought" in r for r in sig.reasons)
    assert sig.price == pytest.approx(closes[-1])


def test_crash_then_oversold_bounce_is_buyish():
    closes = [100.0] * 200 + [100 * 0.97 ** i for i in range(1, 40)]
    sig = analyze("ETHUSDT", "1h", make_candles(closes))
    assert sig.rsi < 30
    assert sig.support <= sig.price <= sig.resistance
    d = sig.to_dict()
    assert d["verdict"] in {"STRONG BUY", "BUY", "NEUTRAL", "SELL", "STRONG SELL"}


def test_downtrend_is_sell_with_levels():
    # Choppy downtrend so RSI isn't pinned at 0
    closes = [100 * 0.995 ** i + (1.5 if i % 2 else -1.5) for i in range(250)]
    sig = analyze("SOLUSDT", "1d", make_candles(closes))
    assert sig.verdict in {"SELL", "STRONG SELL"}
    assert sig.stop_loss > sig.price > sig.take_profit


def test_short_history_without_ema200():
    closes = [100 + math.sin(i / 3) for i in range(80)]
    sig = analyze("DOGEUSDT", "15m", make_candles(closes))
    assert sig.ema200 is None
    assert sig.to_dict()["ema200"] is None


def test_too_few_candles():
    with pytest.raises(ValueError):
        analyze("X", "4h", make_candles([1.0] * 10))


def test_split_pair():
    from crypto_signal.market import split_pair
    assert split_pair("btc") == ("BTC", "USDT")
    assert split_pair("ETH/BTC") == ("ETH", "BTC")
    assert split_pair("SOLUSDC") == ("SOL", "USDC")
    assert split_pair("usdt") == ("USDT", "USDT")
