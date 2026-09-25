import numpy as np
import pandas as pd
import pytest

from crypto_signal import PROFILES, ConfluenceEngine, backtest
from crypto_signal.strategies import FILTERS, TRIGGERS


def make_df(n=3000, drift=0.0003, seed=0):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(drift, 0.01, n)))
    open_ = np.r_[close[0], close[:-1]]
    spread = np.abs(rng.normal(0, 0.004, n)) * close
    idx = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": np.maximum(open_, close) + spread,
                         "low": np.minimum(open_, close) - spread, "close": close}, index=idx)


@pytest.mark.parametrize("name,fn", [*FILTERS.items(), *TRIGGERS.items()])
def test_strategies_vote_in_range(name, fn):
    v = fn(make_df(500))
    assert set(v.unique()) <= {-1, 0, 1}
    assert len(v) == 500


def test_signals_do_not_look_ahead():
    df = make_df(1500)
    eng = ConfluenceEngine("btc")
    full = eng.signals(df)["direction"]
    cut = eng.signals(df.iloc[:1200])["direction"]
    pd.testing.assert_series_equal(full.iloc[:1200], cut)


def test_uptrend_only_goes_long_when_shorts_disabled():
    s = ConfluenceEngine("btc", allow_short=False).signals(make_df(drift=0.001))
    assert (s["direction"] >= 0).all()


def test_gold_session_filter():
    s = ConfluenceEngine("gold").signals(make_df())
    assert set(s.index[s["direction"] != 0].hour) <= set(range(7, 20))


@pytest.mark.parametrize("profile", list(PROFILES))
def test_backtest_runs_and_stats_are_consistent(profile):
    res = backtest(make_df(), ConfluenceEngine(profile))
    log = res["trade_log"]
    assert res["trades"] == len(log)
    if len(log):
        assert res["win_rate"] == pytest.approx((log.r > 0).mean())
        assert (log.entry_time.diff().dropna() > pd.Timedelta(0)).all()
        # a stopped-out trade loses about 1R plus fees (breakeven stops lose ~only fees)
        stops = log[log.reason == "stop"].r
        assert (stops <= 0.0 + 1e-9).all() and (stops >= -1.1).all()


from crypto_signal.basket import BasketConfig, basket_backtest


def test_basket_respects_limits():
    cfg = BasketConfig(max_trades=3, target=1.0, stop=5.0, value_per_point=0.05)
    res = basket_backtest(make_df(), ConfluenceEngine("btc"), cfg)
    log = res["basket_log"]
    assert (log.trades <= 3).all()
    # closed on a bar close past the threshold, so it can overshoot but never close inside the band
    assert ((log.pnl >= 1.0) | (log.pnl <= -5.0)).all()


def test_basket_blows_up_with_huge_lots():
    res = basket_backtest(make_df(), ConfluenceEngine("btc"), BasketConfig(value_per_point=50, stop=1e9))
    assert res["blown_at"] is not None and res["end_equity"] == 0
