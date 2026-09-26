from dexscan.scanner import analyse

NOW = 1_800_000_000_000


def pair(**over):
    p = {"chainId": "solana", "url": "u", "baseToken": {"address": "Tok", "symbol": "TOK", "name": "Token"},
         "priceUsd": "0.01", "priceChange": {"m5": 5, "h1": 40, "h6": 60, "h24": 80},
         "liquidity": {"usd": 150_000}, "fdv": 1_500_000,
         "volume": {"h1": 120_000, "h6": 300_000}, "txns": {"h1": {"buys": 400, "sells": 150},
                                                          "m5": {"buys": 30, "sells": 10}},
         "pairCreatedAt": NOW - 72 * 3.6e6, "info": {"socials": [{"type": "twitter"}]}}
    p.update(over)
    return p


def test_healthy_pump_is_momentum_with_rugcheck_link():
    r = analyse(pair(), now_ms=NOW)
    assert r.verdict == "MOMENTUM" and r.score >= 60 and not r.flags
    assert r.safety_check == "https://rugcheck.xyz/tokens/Tok"


def test_low_liquidity_and_dumped_tokens_are_avoided():
    assert analyse(pair(liquidity={"usd": 5_000}), now_ms=NOW).verdict == "AVOID"
    dumped = analyse(pair(priceChange={"m5": 1, "h1": 5, "h6": -40, "h24": -92}), now_ms=NOW)
    assert dumped.verdict == "AVOID" and any("dumped" in f for f in dumped.flags)


def test_brand_new_and_parabolic_are_not_momentum():
    assert analyse(pair(pairCreatedAt=NOW - 0.5 * 3.6e6), now_ms=NOW).verdict == "AVOID"
    para = analyse(pair(priceChange={"m5": 20, "h1": 900, "h6": 1200, "h24": 1500}), now_ms=NOW)
    assert para.verdict != "MOMENTUM" and any("parabolic" in f for f in para.flags)


def test_evm_tokens_get_honeypot_link_and_missing_fields_do_not_crash():
    r = analyse({"chainId": "base", "baseToken": {"address": "0xabc"}}, now_ms=NOW)
    assert r.safety_check == "https://honeypot.is/?address=0xabc" and r.verdict in {"AVOID", "WEAK"}
