"""The bot's brain: a Grok-style persona on Claude, with live market tools and web search."""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone

import anthropic

from .config import Settings
from .market import MarketData, MarketDataError
from .signals import analyze

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 8

PERSONA = """You are {name}, a crypto-native AI that people chat with in Telegram DMs and \
tag in group chats. Your vibe is inspired by Grok: witty, irreverent, and brutally honest, \
with a sense of humor and zero corporate filler. You are your own bot, not Grok and not made by \
xAI; if someone asks what you are, say you're {name}, powered by Claude.

How you operate:
- Truth first. Get the facts right, then make them fun. Never invent prices, stats, dates or news.
- For anything about current prices, charts or market conditions, call your market tools. For news, \
narratives, rumors, "is this true?" checks or anything after your training data, use web search. \
Quote the numbers you got back, not remembered ones.
- When someone tags you under another message ("is this true?", "explain this", "ratio"), the \
message they replied to is included. Fact-check or explain it directly and say plainly whether it \
holds up.
- Have opinions and take a side when the data supports one. Call out hype, scams, rug-pull \
red flags and bad takes. Don't hedge everything into mush.
- Trading signals come from get_signal: give the verdict, the 2-3 reasons that matter, and the \
levels (support, resistance, stop, target). Remind people briefly that it's not financial advice \
and markets can do anything; one short line, not a lecture.
- Keep it tight: chat replies are usually 1-6 sentences. Go longer only when asked to explain \
something in depth.
- Output plain text for Telegram. No markdown tables or headers; simple dashes for lists are fine, \
emojis sparingly.
"""

MODES = {
    "fun": "Mode: FUN. Lean into the humor: roast bad takes, use crypto slang (ngmi, wagmi, rekt, "
    "cope, touch grass), be playful and edgy but never cruel, hateful or harassing. Accuracy is "
    "still non-negotiable.",
    "regular": "Mode: REGULAR. Still direct and honest with a light touch of wit, but mostly "
    "clear, professional and to the point.",
}

CUSTOM_TOOLS = [
    {
        "name": "get_price",
        "description": "Live price and market stats (USD) for a cryptocurrency: price, 1h/24h/7d "
        "change, 24h high/low, market cap and rank, volume, all-time high. Use for any question "
        "about what a coin is trading at or how it has moved.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker or name, e.g. BTC, ETH, solana, PEPE"}
            },
            "required": ["symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_signal",
        "description": "Technical-analysis trading signal from Binance candles: RSI, EMA20/50/200, "
        "MACD, Bollinger bands, ATR, support/resistance, and a scored verdict (STRONG BUY to "
        "STRONG SELL) with suggested stop-loss and take-profit. Use when asked for a signal, "
        "setup, TA, entry, or 'should I long/short X'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "Ticker, e.g. BTC or ETHUSDT"},
                "interval": {
                    "type": "string",
                    "enum": ["15m", "30m", "1h", "4h", "1d", "1w"],
                    "description": "Candle timeframe. Default 4h; use 15m/1h for scalps, 1d/1w for swing.",
                },
            },
            "required": ["symbol"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_market_overview",
        "description": "Whole-market snapshot: total market cap and 24h change, BTC/ETH dominance, "
        "top 10 coins with 24h change, and currently trending coins. Use for 'how's the market', "
        "'what's pumping', 'what's trending'.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]

WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}


@dataclass
class ChatState:
    mode: str
    history: deque = field(default_factory=deque)  # (user_text, assistant_text) pairs
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class Brain:
    def __init__(
        self,
        settings: Settings,
        market: MarketData,
        client: anthropic.AsyncAnthropic | None = None,
    ):
        self.settings = settings
        self.market = market
        self.client = client or anthropic.AsyncAnthropic()
        self.tools = CUSTOM_TOOLS + ([WEB_SEARCH_TOOL] if settings.enable_web_search else [])
        self._system = PERSONA.format(name=settings.bot_name)
        self._chats: dict[str, ChatState] = defaultdict(
            lambda: ChatState(mode=settings.default_mode if settings.default_mode in MODES else "fun")
        )

    # ---- chat state ------------------------------------------------------

    def set_mode(self, chat_id: str, mode: str) -> None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {list(MODES)}")
        self._chats[chat_id].mode = mode

    def get_mode(self, chat_id: str) -> str:
        return self._chats[chat_id].mode

    def reset(self, chat_id: str) -> None:
        self._chats[chat_id].history.clear()

    # ---- tools -----------------------------------------------------------

    async def run_tool(self, name: str, args: dict) -> str:
        if name == "get_price":
            return json.dumps(await self.market.price(args["symbol"]))
        if name == "get_signal":
            interval = args.get("interval") or "4h"
            pair, candles = await self.market.candles(args["symbol"], interval)
            return json.dumps(analyze(pair, interval, candles).to_dict())
        if name == "get_market_overview":
            return json.dumps(await self.market.overview())
        raise ValueError(f"unknown tool {name}")

    async def _tool_result(self, block) -> dict:
        try:
            content = await self.run_tool(block.name, dict(block.input or {}))
            return {"type": "tool_result", "tool_use_id": block.id, "content": content}
        except (MarketDataError, ValueError, KeyError) as exc:
            return {"type": "tool_result", "tool_use_id": block.id, "content": f"Error: {exc}",
                    "is_error": True}

    # ---- main entry point ------------------------------------------------

    async def reply(
        self,
        chat_id: str,
        text: str,
        *,
        user_name: str | None = None,
        replied_to: str | None = None,
        replied_to_author: str | None = None,
    ) -> str:
        state = self._chats[chat_id]
        async with state.lock:
            user_turn = self._format_user_turn(text, user_name, replied_to, replied_to_author)
            messages: list[dict] = []
            for past_user, past_bot in state.history:
                messages.append({"role": "user", "content": past_user})
                messages.append({"role": "assistant", "content": past_bot})
            messages.append({"role": "user", "content": user_turn})

            answer = await self._run(messages, state.mode)

            state.history.append((user_turn, answer))
            while len(state.history) > self.settings.history_turns:
                state.history.popleft()
            return answer

    def _format_user_turn(self, text, user_name, replied_to, replied_to_author) -> str:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        parts = [f"[{now}]"]
        if replied_to:
            who = replied_to_author or "someone"
            parts.append(f"They are replying to this message from {who}:\n<<<\n{replied_to}\n>>>")
        parts.append(f"{user_name or 'User'}: {text}")
        return "\n".join(parts)

    async def _run(self, messages: list[dict], mode: str) -> str:
        system = [
            {"type": "text", "text": self._system},
            {"type": "text", "text": MODES[mode], "cache_control": {"type": "ephemeral"}},
        ]
        for _ in range(MAX_TOOL_ROUNDS):
            response = await self.client.beta.messages.create(
                model=self.settings.model,
                max_tokens=16000,
                system=system,
                tools=self.tools,
                messages=messages,
                thinking={"type": "adaptive"},
                output_config={"effort": self.settings.effort},
                # If the primary model declines, the API retries on a recommended fallback model.
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )

            if response.stop_reason == "refusal":
                return "Yeah... I'm not touching that one. Ask me something else."

            if response.stop_reason == "pause_turn":
                # A long server-side web search paused mid-turn; send it back to continue.
                messages.append({"role": "assistant", "content": response.content})
                continue

            if response.stop_reason == "tool_use":
                messages.append({"role": "assistant", "content": response.content})
                tool_uses = [b for b in response.content if b.type == "tool_use"]
                results = await asyncio.gather(*(self._tool_result(b) for b in tool_uses))
                messages.append({"role": "user", "content": list(results)})
                continue

            text = _final_text(response.content)
            if response.stop_reason == "max_tokens":
                text += " …(cut off)"
            return text or "🤐 Drew a blank on that one. Try rephrasing?"

        log.warning("tool loop hit MAX_TOOL_ROUNDS")
        return "I went down a research rabbit hole and ran out of steps. Try a narrower question?"


def _final_text(content) -> str:
    return "".join(b.text for b in content if b.type == "text").strip()
