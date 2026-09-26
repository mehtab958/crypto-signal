"""Exercises the agent loop with a fake Claude client and fake market data (no network)."""

import json
from types import SimpleNamespace as NS

from crypto_signal.brain import Brain
from crypto_signal.config import Settings
from crypto_signal.market import MarketDataError
from crypto_signal.signals import Candle


def settings(**kw):
    base = dict(
        telegram_token=None, bot_name="TestBot", model="claude-opus-5", effort="medium",
        default_mode="fun", history_turns=2, enable_web_search=True,
        binance_base_url="x", okx_base_url="x", coingecko_base_url="x", coingecko_api_key=None,
    )
    base.update(kw)
    return Settings(**base)


class FakeMarket:
    async def price(self, symbol):
        if symbol == "NOPE":
            raise MarketDataError("no coin found for 'NOPE'")
        return {"symbol": symbol, "price_usd": 123.0}

    async def candles(self, symbol, interval="4h", limit=300):
        closes = [100 * 1.01 ** i for i in range(250)]
        return symbol + "USDT", [Candle(i, c, c * 1.01, c * 0.99, c, 1.0) for i, c in enumerate(closes)]

    async def overview(self):
        return {"btc_dominance_pct": 55}


class FakeMessages:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        # Snapshot messages, since the brain appends to the same list between calls
        self.calls.append({**kwargs, "messages": list(kwargs["messages"])})
        return self.responses.pop(0)


def fake_client(responses):
    msgs = FakeMessages(responses)
    return NS(beta=NS(messages=msgs)), msgs


def text(t):
    return NS(type="text", text=t)


def tool_use(id_, name, inp):
    return NS(type="tool_use", id=id_, name=name, input=inp)


async def test_plain_reply_and_history():
    client, msgs = fake_client([
        NS(stop_reason="end_turn", content=[text("gm ser")]),
        NS(stop_reason="end_turn", content=[text("still here")]),
    ])
    brain = Brain(settings(), FakeMarket(), client)
    assert await brain.reply("c1", "gm", user_name="Ann") == "gm ser"
    assert await brain.reply("c1", "you there?") == "still here"
    second = msgs.calls[1]
    assert [m["role"] for m in second["messages"]] == ["user", "assistant", "user"]
    assert second["messages"][1]["content"] == "gm ser"
    assert "Ann: gm" in second["messages"][0]["content"]
    assert second["fallbacks"] == "default"
    assert second["thinking"] == {"type": "adaptive"}
    assert any(t.get("name") == "web_search" for t in second["tools"])


async def test_tool_loop_runs_tools_in_parallel_single_message():
    client, msgs = fake_client([
        NS(stop_reason="tool_use", content=[
            text("checking"),
            tool_use("t1", "get_price", {"symbol": "BTC"}),
            tool_use("t2", "get_signal", {"symbol": "BTC", "interval": "1h"}),
            tool_use("t3", "get_price", {"symbol": "NOPE"}),
        ]),
        NS(stop_reason="end_turn", content=[text("BTC is pumping")]),
    ])
    brain = Brain(settings(), FakeMarket(), client)
    assert await brain.reply("c", "btc?") == "BTC is pumping"
    results = msgs.calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2", "t3"]
    assert json.loads(results[0]["content"])["price_usd"] == 123.0
    sig = json.loads(results[1]["content"])
    assert sig["symbol"] == "BTCUSDT" and sig["interval"] == "1h"
    assert results[2]["is_error"] is True


async def test_pause_turn_continues():
    paused = [NS(type="server_tool_use", id="s1", name="web_search", input={"query": "x"})]
    client, msgs = fake_client([
        NS(stop_reason="pause_turn", content=paused),
        NS(stop_reason="end_turn", content=[text("done")]),
    ])
    brain = Brain(settings(), FakeMarket(), client)
    assert await brain.reply("c", "news?") == "done"
    assert msgs.calls[1]["messages"][-1] == {"role": "assistant", "content": paused}


async def test_refusal_and_reply_context_and_modes():
    client, msgs = fake_client([NS(stop_reason="refusal", content=[])])
    brain = Brain(settings(enable_web_search=False), FakeMarket(), client)
    brain.set_mode("g", "regular")
    out = await brain.reply("g", "is this true?", replied_to="ETH to 100k tomorrow", replied_to_author="Bob")
    assert "not touching" in out
    call = msgs.calls[0]
    assert "ETH to 100k tomorrow" in call["messages"][-1]["content"]
    assert "Bob" in call["messages"][-1]["content"]
    assert "REGULAR" in call["system"][1]["text"]
    assert not any(t.get("name") == "web_search" for t in call["tools"])


async def test_history_is_trimmed():
    client, msgs = fake_client([NS(stop_reason="end_turn", content=[text(str(i))]) for i in range(4)])
    brain = Brain(settings(history_turns=2), FakeMarket(), client)
    for i in range(4):
        await brain.reply("c", f"q{i}")
    assert len(msgs.calls[3]["messages"]) == 5  # 2 remembered exchanges + new question
    brain.reset("c")
    assert len(brain._chats["c"].history) == 0
