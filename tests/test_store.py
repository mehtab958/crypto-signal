import time

from whalebot.safety import SafetyReport
from whalebot.scoring import build_signal
from whalebot.socials import SocialReport
from whalebot.store import Store
from whalebot.whales import WhaleTrade

from .test_scoring import make_pair


def test_whale_trade_dedupe_and_lookup(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    t = WhaleTrade(wallet="w", wallet_label="w", weight=1, chain="solana", token="MINT", side="buy",
                   amount=1, quote_amount=1, timestamp=int(time.time()), tx="sig")
    assert s.add_whale_trades([t]) == [t]
    assert s.add_whale_trades([t]) == []
    assert len(s.recent_whale_buys("solana", "mint", int(time.time()) - 60)) == 1


def test_signal_dedupe_and_outcomes(tmp_path):
    s = Store(str(tmp_path / "t.db"))
    sig = build_signal(make_pair(), SafetyReport(ok=True, score=1), SocialReport(score=0), [])
    assert s.should_alert("solana", "MINT", sig.score, new_whale=False)
    sid = s.add_signal(sig)
    assert not s.should_alert("solana", "MINT", sig.score, new_whale=False)
    assert s.should_alert("solana", "MINT", sig.score, new_whale=True)

    s.db.execute("UPDATE signals SET created_at=created_at-7200 WHERE id=?", (sid,))
    due = s.due_outcomes([15, 60, 240])
    assert sorted(m for _, m in due) == [15, 60]
    s.add_outcome(sid, 15, price=0.003, entry=0.001)
    perf = {r["minutes"]: r for r in s.performance()}
    assert perf[15]["x2"] == 1 and abs(perf[15]["avg_mult"] - 3) < 1e-9
