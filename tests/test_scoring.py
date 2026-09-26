import time

from whalebot.config import Filters, Safety, Whale
from whalebot.dexscreener import Pair
from whalebot.safety import SafetyReport, evaluate_goplus, evaluate_rugcheck
from whalebot.scoring import build_signal, hard_filter, momentum_score, whale_score
from whalebot.socials import SocialReport, score_socials, telegram_username
from whalebot.whales import WhaleTrade, parse_evm_transfers, parse_solana_tx


def make_pair(**over) -> Pair:
    raw = {
        "chainId": "solana", "dexId": "raydium", "pairAddress": "P", "url": "https://dexscreener.com/x",
        "baseToken": {"address": "MINT", "symbol": "TEST", "name": "Test"},
        "priceUsd": "0.001",
        "liquidity": {"usd": 40_000},
        "marketCap": 200_000, "fdv": 200_000,
        "pairCreatedAt": int((time.time() - 1800) * 1000),
        "txns": {"m5": {"buys": 60, "sells": 20}, "h1": {"buys": 400, "sells": 200}},
        "volume": {"m5": 20_000, "h1": 100_000},
        "priceChange": {"m5": 12, "h1": 60},
        "info": {"socials": [{"type": "twitter", "url": "https://x.com/test"}]},
    }
    raw.update(over)
    return Pair.from_api(raw)


def test_pair_parsing_bonding_curve():
    p = make_pair(liquidity=None)
    assert p.is_bonding_curve
    assert p.socials["twitter"] == "https://x.com/test"
    assert 0.4 < p.age_hours < 0.6


def test_hard_filter_accepts_good_pair():
    assert hard_filter(make_pair(), Filters()) is None


def test_hard_filter_rejects():
    f = Filters()
    assert "liquidity" in hard_filter(make_pair(liquidity={"usd": 500}), f)
    assert "too old" in hard_filter(make_pair(pairCreatedAt=int((time.time() - 3 * 86400) * 1000)), f)
    assert "late" in hard_filter(make_pair(priceChange={"m5": 5, "h1": 900}), f)
    assert "mcap" in hard_filter(make_pair(marketCap=50_000_000), f)
    # bonding curve pairs skip the liquidity check
    assert hard_filter(make_pair(liquidity=None), f) is None


def test_momentum_rewards_buy_pressure_and_acceleration():
    strong, reasons, _ = momentum_score(make_pair())
    weak, _, warnings = momentum_score(make_pair(
        txns={"m5": {"buys": 5, "sells": 30}, "h1": {"buys": 100, "sells": 200}},
        volume={"m5": 500, "h1": 100_000}, priceChange={"m5": -8, "h1": -20}))
    assert 0 <= weak < strong <= 35
    assert any("buy pressure" in r for r in reasons)
    assert any("sellers" in w for w in warnings)


def _trade(wallet, weight=1.0):
    return WhaleTrade(wallet=wallet, wallet_label=wallet, weight=weight, chain="solana", token="MINT",
                      side="buy", amount=1, quote_amount=1, timestamp=0, tx=wallet)


def test_whale_confluence_scores_higher():
    one, _ = whale_score([_trade("a")])
    two, _ = whale_score([_trade("a"), _trade("b")])
    dup, _ = whale_score([_trade("a"), _trade("a")])
    assert one == dup == 15
    assert two > one
    assert whale_score([])[0] == 0


def test_build_signal_totals():
    sig = build_signal(make_pair(), SafetyReport(ok=True, score=1.0), SocialReport(score=0.5, has_twitter=True),
                       [_trade("a")])
    assert sig.score == round(sum(sig.parts.values()), 1)
    assert sig.parts["whales"] == 15 and sig.parts["safety"] == 20 and sig.parts["social"] == 5
    assert sig.score <= 100


def test_rugcheck_danger_rejects():
    cfg = Safety()
    good = evaluate_rugcheck({"score_normalised": 3, "risks": [], "lpLockedPct": 100}, cfg)
    bad = evaluate_rugcheck({"score_normalised": 5, "risks": [{"name": "Freeze Authority still enabled",
                                                                "level": "danger"}]}, cfg)
    risky = evaluate_rugcheck({"score_normalised": 80, "risks": []}, cfg)
    assert good.ok and good.score > 0.9
    assert not bad.ok and "Freeze Authority" in bad.flags[0]
    assert not risky.ok


def test_goplus_honeypot_and_tax():
    cfg = Safety()
    assert not evaluate_goplus({"is_honeypot": "1"}, cfg).ok
    assert not evaluate_goplus({"buy_tax": "0.02", "sell_tax": "0.25"}, cfg).ok
    whale_heavy = {"holders": [{"percent": "0.3", "is_locked": 0, "is_contract": 0},
                               {"percent": "0.3", "is_locked": 0, "is_contract": 0}]}
    assert not evaluate_goplus(whale_heavy, cfg).ok
    clean = evaluate_goplus({"buy_tax": "0", "sell_tax": "0", "holders": [
        {"percent": "0.5", "is_locked": 1, "is_contract": 0}]}, cfg)  # locked LP/burn doesn't count
    assert clean.ok and clean.score > 0.9


def test_socials():
    assert telegram_username("https://t.me/mytoken_portal") == "mytoken_portal"
    assert telegram_username("https://t.me/joinchat/abcdef") is None
    rich, _ = score_socials(True, True, True, True, 2000, False, 0)
    post_only, notes = score_socials(True, False, False, None, None, True, 0)
    none, none_notes = score_socials(False, False, False, None, None, False, 0)
    assert rich > post_only > none == 0
    assert "no socials" in none_notes and any("post" in n for n in notes)


WHALE = "Wha1e111111111111111111111111111111111111111"


def _sol_tx(signer, pre_tok, post_tok, pre_sol, post_sol):
    return {
        "blockTime": 1_700_000_000,
        "meta": {"err": None, "preBalances": [pre_sol], "postBalances": [post_sol],
                 "preTokenBalances": pre_tok, "postTokenBalances": post_tok},
        "transaction": {"message": {"accountKeys": [{"pubkey": signer, "signer": True}]}},
    }


def _bal(mint, amt, owner=WHALE):
    return {"mint": mint, "owner": owner, "uiTokenAmount": {"uiAmount": amt}}


def test_parse_solana_buy_and_sell():
    whale = Whale(address=WHALE, label="w")
    buy = parse_solana_tx(_sol_tx(WHALE, [], [_bal("MEME", 1000)], 5_000_000_000, 3_000_000_000), whale, "sig1")
    assert len(buy) == 1 and buy[0].side == "buy" and buy[0].amount == 1000
    assert abs(buy[0].quote_amount - 2.0) < 1e-9
    sell = parse_solana_tx(_sol_tx(WHALE, [_bal("MEME", 1000)], [_bal("MEME", 0)], 1, 2), whale, "sig2")
    assert sell[0].side == "sell"


def test_parse_solana_ignores_airdrops_and_quote_tokens():
    whale = Whale(address=WHALE, label="w")
    airdrop = _sol_tx("SomeoneElse", [], [_bal("SPAM", 1e9)], 1, 1)
    assert parse_solana_tx(airdrop, whale, "s") == []
    usdc = _sol_tx(WHALE, [], [_bal("EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", 100)], 1, 1)
    assert parse_solana_tx(usdc, whale, "s") == []


def test_parse_evm_transfers():
    whale = Whale(address="0xabc", chain="base", label="w")
    transfers = [
        {"hash": "0x1", "to": "0xabc", "from": "0xpool", "contractAddress": "0xMEME", "tokenSymbol": "MEME",
         "value": "5000000000000000000", "tokenDecimal": "18", "timeStamp": "100"},
        {"hash": "0x1", "to": "0xpool", "from": "0xabc", "contractAddress": "0xweth", "tokenSymbol": "WETH",
         "value": "1", "tokenDecimal": "18", "timeStamp": "100"},
        {"hash": "0x2", "to": "0xabc", "from": "0xscam", "contractAddress": "0xSPAM", "tokenSymbol": "SPAM",
         "value": "1", "tokenDecimal": "0", "timeStamp": "100"},
    ]
    trades = parse_evm_transfers(transfers, {"0x1"}, whale, "base", min_ts=50)
    assert [(t.token, t.side, t.amount) for t in trades] == [("0xmeme", "buy", 5.0)]
    assert parse_evm_transfers(transfers, {"0x1"}, whale, "base", min_ts=200) == []
