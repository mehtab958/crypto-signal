from crypto_signal.telegram_bot import format_price, split_message, strip_mention


def test_split_message_respects_limit():
    text = ("word " * 3000).strip()
    chunks = split_message(text, 100)
    assert all(len(c) <= 100 for c in chunks)
    assert " ".join(chunks) == text


def test_split_short_message():
    assert split_message("gm") == ["gm"]


def test_strip_mention():
    assert strip_mention("@SignalBot is this true?", "SignalBot") == "is this true?"


def test_format_price():
    out = format_price({
        "name": "Bitcoin", "symbol": "BTC", "market_cap_rank": 1, "price_usd": 65000.5,
        "change_1h_pct": 0.1, "change_24h_pct": -2.5, "change_7d_pct": None,
        "low_24h": 64000, "high_24h": 66000, "market_cap_usd": 1.3e12,
        "volume_24h_usd": 3.2e10, "ath_usd": 110000, "ath_change_pct": -40.9,
    })
    assert "#1 Bitcoin (BTC)" in out and "$65,000.50" in out and "🔴 -2.50%" in out
