import json

import numpy as np
import pandas as pd
import pytest

from crypto_signal import backtest as bt
from crypto_signal import bot as botmod
from crypto_signal import portfolio as pf
from crypto_signal.data import load_csv
from crypto_signal.research import extra_params
from crypto_signal.strategies import REGISTRY


@pytest.fixture(scope="module")
def df4h():
    return load_csv("BTCUSD", "4h", start="2021-01-01", end="2022-06-01")


@pytest.mark.parametrize("name", list(REGISTRY))
def test_strategies_have_no_lookahead(df4h, name):
    """The signal at bar t must not change when future bars are added."""
    s = REGISTRY[name](**extra_params(name, "4h"))
    full = s.generate(df4h)
    for n in [1500, 2000, 2600]:
        part = s.generate(df4h.iloc[:n])
        pd.testing.assert_series_equal(part, full.iloc[:n], check_names=False)
    assert full.between(0, 1).all()


def test_buy_and_hold_matches_price(df4h):
    r = bt.buy_and_hold(df4h, "4h", fee=0, slippage=0)
    assert r.equity.iloc[-1] / r.equity.iloc[0] == pytest.approx(
        df4h["close"].iloc[-1] / df4h["close"].iloc[0], rel=1e-9)


def test_costs_are_charged(df4h):
    flip = pd.Series(np.arange(len(df4h)) % 2, index=df4h.index, dtype=float)
    free = bt.run(df4h, flip, "4h", fee=0, slippage=0)
    paid = bt.run(df4h, flip, "4h", fee=0.001, slippage=0)
    assert paid.equity.iloc[-1] < free.equity.iloc[-1]


def test_position_applies_from_next_bar():
    idx = pd.date_range("2024-01-01", periods=4, freq="4h", tz="UTC")
    df = pd.DataFrame({"open": 1, "high": 1, "low": 1, "close": [100, 200, 200, 100]}, index=idx)
    pos = pd.Series([0, 1, 1, 0], index=idx, dtype=float)
    r = bt.run(df, pos, "4h", fee=0, slippage=0, initial=1)
    # entered at close of bar 1 (200): misses the 100->200 jump, takes the 200->100 drop
    assert r.equity.iloc[-1] == pytest.approx(0.5)


def test_daily_signal_not_used_before_daily_close():
    idx4 = pd.date_range("2024-01-01", periods=12, freq="4h", tz="UTC")
    idx1 = pd.date_range("2024-01-01", periods=2, freq="1D", tz="UTC")

    class Const(REGISTRY["ema_trend"]):
        def generate(self, df):
            return pd.Series([1.0, 0.0], index=df.index)

    frames = {"4h": pd.DataFrame({"close": 1.0}, index=idx4),
              "1d": pd.DataFrame({"close": 1.0}, index=idx1)}
    pos = pf.member_positions([pf.Member(Const(), "1d")], frames, "4h").iloc[:, 0]
    # day-1 candle closes at 2024-01-02 00:00 = close of the 4h bar labelled 20:00
    assert (pos.iloc[:5] == 0).all() and pos.iloc[5] == 1.0 and pos.iloc[6] == 1.0


def test_portfolio_config_roundtrip(tmp_path):
    _, members = pf.load("config/portfolio.json")
    assert members
    pf.save(tmp_path / "p.json", members)
    _, again = pf.load(tmp_path / "p.json")
    assert [m.strategy.params for m in again] == [m.strategy.params for m in members]


class FakeExchange:
    """Replays bundled candles up to a cut-off time, like an exchange would."""

    def __init__(self, now):
        self.now = pd.Timestamp(now, tz="UTC")
        self.data = {"4h": load_csv("BTCUSD", "4h", start="2020-01-01"),
                     "1d": load_csv("BTCUSD", "1d", start="2018-01-01")}

    def parse_timeframe(self, tf):
        return {"4h": 4 * 3600, "1d": 86400}[tf]

    def milliseconds(self):
        return self.now.value // 10**6

    def fetch_ohlcv(self, symbol, timeframe, limit):
        d = self.data[timeframe]
        d = d[d.index <= self.now].tail(limit)
        return [[t.value // 10**6, *row] for t, row in zip(d.index, d.to_numpy().tolist())]


def make_bot(tmp_path, now, **over):
    cfg = {**botmod.DEFAULTS, "state_file": str(tmp_path / "state.json"), **over}
    return botmod.Bot(cfg, exchange=FakeExchange(now))


def test_bot_signal_matches_backtest(tmp_path):
    now = "2024-03-01 00:10"
    bot = make_bot(tmp_path, now)
    sig = bot.signal("BTC/USDT")
    frames = {tf: load_csv("BTCUSD", tf, start="2016-01-01") for tf in ["4h", "1d"]}
    bt_pos = pf.combine(bot.members, frames, "4h")
    # the last closed 4h candle at 00:10 is the one opened at 20:00 the previous day
    assert sig["bar"] == pd.Timestamp("2024-02-29 20:00", tz="UTC")
    assert sig["target"] == pytest.approx(bt_pos.loc[sig["bar"]], abs=1e-9)


def test_bot_paper_trades_and_persists(tmp_path):
    bot = make_bot(tmp_path, "2024-03-01 00:10")
    bot.step()
    state = json.loads((tmp_path / "state.json").read_text())
    target = bot.signal("BTC/USDT")["target"]
    if target > bot.cfg["rebalance_threshold"]:
        assert state["fills"] and state["fills"][0]["side"] == "buy"
    assert state["equity"] == pytest.approx(10_000, rel=0.01)
    # restart picks up the same account
    again = make_bot(tmp_path, "2024-03-01 04:10")
    assert again.state["paper"] == state["paper"]


def test_kill_switch_flattens(tmp_path):
    bot = make_bot(tmp_path, "2024-03-01 00:10")
    bot.state["paper"]["BTC/USDT"] = {"cash": 0.0, "qty": 0.2}
    bot.state["peak_equity"] = 1_000_000.0
    bot.step()
    assert bot.state["halted"]
    assert bot.state["paper"]["BTC/USDT"]["qty"] == 0
