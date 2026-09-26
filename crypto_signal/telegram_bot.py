"""Telegram front-end. DMs: replies to everything. Groups: replies when tagged or replied to."""

from __future__ import annotations

import logging
import time

import anthropic
from telegram import Message, Update
from telegram.constants import ChatAction, ChatType
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .brain import Brain
from .config import Settings
from .market import MarketData, MarketDataError

log = logging.getLogger(__name__)

TELEGRAM_LIMIT = 4096
USER_COOLDOWN_SECONDS = 3.0


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    """Split on paragraph/line boundaries so long answers fit Telegram's message limit."""
    chunks: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = text.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


def strip_mention(text: str, username: str) -> str:
    return text.replace(f"@{username}", "").strip() if username else text.strip()


def _author(msg: Message | None) -> str | None:
    if msg is None:
        return None
    if msg.from_user:
        return msg.from_user.full_name
    if msg.sender_chat:
        return msg.sender_chat.title
    return None


class TelegramBot:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.market = MarketData(settings)
        self.brain = Brain(settings, self.market)
        self._last_seen: dict[int, float] = {}

    def build(self) -> Application:
        if not self.settings.telegram_token:
            raise SystemExit("TELEGRAM_BOT_TOKEN is not set (see .env.example)")
        app = ApplicationBuilder().token(self.settings.telegram_token).concurrent_updates(True).build()
        app.add_handler(CommandHandler(["start", "help"], self.cmd_help))
        app.add_handler(CommandHandler("fun", self.cmd_fun))
        app.add_handler(CommandHandler("regular", self.cmd_regular))
        app.add_handler(CommandHandler("reset", self.cmd_reset))
        app.add_handler(CommandHandler("price", self.cmd_price))
        app.add_handler(CommandHandler("signal", self.cmd_signal))
        app.add_handler(CommandHandler("market", self.cmd_market))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.on_text))
        app.add_error_handler(self.on_error)
        return app

    # ---- commands --------------------------------------------------------

    async def cmd_help(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        name = self.settings.bot_name
        bot_user = ctx.bot.username
        await update.effective_message.reply_text(
            f"gm, I'm {name} 🤖 your unfiltered crypto copilot.\n\n"
            "Just talk to me. In groups, tag me "
            f"(@{bot_user}) or reply to one of my messages. Reply to any post with "
            f"\"@{bot_user} is this true?\" and I'll fact-check it.\n\n"
            "/price BTC - live price\n"
            "/signal ETH 4h - TA signal (15m 30m 1h 4h 1d 1w)\n"
            "/market - market overview and what's trending\n"
            "/fun - unhinged mode (default)\n"
            "/regular - professional mode\n"
            "/reset - forget this chat\n\n"
            "Not financial advice. I'm a bot, not your mom."
        )

    async def cmd_fun(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        self.brain.set_mode(self._chat_key(update), "fun")
        await update.effective_message.reply_text("Fun mode on. Let's cook 🔥")

    async def cmd_regular(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        self.brain.set_mode(self._chat_key(update), "regular")
        await update.effective_message.reply_text("Regular mode. Suit and tie on 👔")

    async def cmd_reset(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        self.brain.reset(self._chat_key(update))
        await update.effective_message.reply_text("Memory wiped. Who are you again? 🫥")

    async def cmd_price(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        # Direct data path: fast and free, no LLM call.
        symbol = ctx.args[0] if ctx.args else "BTC"
        try:
            p = await self.market.price(symbol)
        except MarketDataError as exc:
            await update.effective_message.reply_text(f"Couldn't fetch that: {exc}")
            return
        await update.effective_message.reply_text(format_price(p))

    async def cmd_signal(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        symbol = ctx.args[0] if ctx.args else "BTC"
        interval = ctx.args[1] if len(ctx.args) > 1 else "4h"
        await self._answer(update, ctx, f"Give me your {interval} signal for {symbol}.")

    async def cmd_market(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        await self._answer(update, ctx, "How's the market looking right now? What's trending?")

    # ---- free text -------------------------------------------------------

    async def on_text(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        if msg is None or not msg.text:
            return
        chat = update.effective_chat
        bot_username = ctx.bot.username or ""

        if chat.type != ChatType.PRIVATE:
            mentioned = f"@{bot_username}".lower() in msg.text.lower()
            replying_to_bot = bool(
                msg.reply_to_message
                and msg.reply_to_message.from_user
                and msg.reply_to_message.from_user.id == ctx.bot.id
            )
            if not (mentioned or replying_to_bot):
                return

        text = strip_mention(msg.text, bot_username) or "?"
        await self._answer(update, ctx, text)

    async def _answer(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str) -> None:
        msg = update.effective_message
        user = update.effective_user

        if user is not None:
            now = time.monotonic()
            if now - self._last_seen.get(user.id, 0.0) < USER_COOLDOWN_SECONDS:
                return
            self._last_seen[user.id] = now

        replied = msg.reply_to_message
        replied_text = None
        if replied is not None and not (replied.from_user and replied.from_user.id == ctx.bot.id):
            replied_text = replied.text or replied.caption

        await ctx.bot.send_chat_action(chat_id=msg.chat_id, action=ChatAction.TYPING)
        try:
            answer = await self.brain.reply(
                self._chat_key(update),
                text,
                user_name=user.first_name if user else None,
                replied_to=replied_text,
                replied_to_author=_author(replied) if replied_text else None,
            )
        except anthropic.RateLimitError:
            answer = "I'm getting hammered right now 🥵 try again in a minute."
        except anthropic.APIStatusError as exc:
            log.exception("Claude API error")
            answer = f"My brain glitched (API error {exc.status_code}). Try again shortly."
        except anthropic.APIConnectionError:
            log.exception("Claude connection error")
            answer = "Can't reach my brain right now. Try again shortly."

        for chunk in split_message(answer):
            await msg.reply_text(chunk, disable_web_page_preview=True)

    # ---- misc ------------------------------------------------------------

    @staticmethod
    def _chat_key(update: Update) -> str:
        return str(update.effective_chat.id)

    async def on_error(self, update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("Unhandled error", exc_info=ctx.error)


def _fmt_usd(x: float | None) -> str:
    if x is None:
        return "n/a"
    if x >= 1e9:
        return f"${x / 1e9:,.2f}B"
    if x >= 1e6:
        return f"${x / 1e6:,.2f}M"
    if x >= 1:
        return f"${x:,.2f}"
    return f"${x:.8g}"


def _fmt_pct(x: float | None) -> str:
    if x is None:
        return "n/a"
    arrow = "🟢" if x >= 0 else "🔴"
    return f"{arrow} {x:+.2f}%"


def format_price(p: dict) -> str:
    rank = f"#{p['market_cap_rank']} " if p.get("market_cap_rank") else ""
    return (
        f"{rank}{p['name']} ({p['symbol']})\n"
        f"Price: {_fmt_usd(p['price_usd'])}\n"
        f"1h: {_fmt_pct(p['change_1h_pct'])}  24h: {_fmt_pct(p['change_24h_pct'])}  "
        f"7d: {_fmt_pct(p['change_7d_pct'])}\n"
        f"24h range: {_fmt_usd(p['low_24h'])} - {_fmt_usd(p['high_24h'])}\n"
        f"MCap: {_fmt_usd(p['market_cap_usd'])}  Vol: {_fmt_usd(p['volume_24h_usd'])}\n"
        f"ATH: {_fmt_usd(p['ath_usd'])} ({_fmt_pct(p['ath_change_pct'])} from ATH)"
    )
