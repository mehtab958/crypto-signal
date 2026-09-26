"""Entry point.

    python -m crypto_signal          # run the Telegram bot
    python -m crypto_signal chat     # chat with the bot in your terminal (no Telegram needed)
"""

from __future__ import annotations

import asyncio
import logging
import sys

from .config import Settings


async def _terminal_chat(settings: Settings) -> None:
    from .brain import Brain
    from .market import MarketData

    market = MarketData(settings)
    brain = Brain(settings, market)
    print(f"{settings.bot_name} ready. Commands: /fun /regular /reset /quit\n")
    try:
        while True:
            try:
                text = (await asyncio.to_thread(input, "you> ")).strip()
            except EOFError:
                break
            if not text:
                continue
            if text in {"/quit", "/exit"}:
                break
            if text in {"/fun", "/regular"}:
                brain.set_mode("cli", text[1:])
                print(f"[mode: {text[1:]}]\n")
                continue
            if text == "/reset":
                brain.reset("cli")
                print("[memory cleared]\n")
                continue
            print(f"{settings.bot_name}> {await brain.reply('cli', text, user_name='You')}\n")
    finally:
        await market.aclose()


def main() -> None:
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = Settings.from_env()

    if len(sys.argv) > 1 and sys.argv[1] == "chat":
        asyncio.run(_terminal_chat(settings))
        return

    from .telegram_bot import TelegramBot

    app = TelegramBot(settings).build()
    logging.getLogger(__name__).info("%s is live, polling Telegram...", settings.bot_name)
    app.run_polling(allowed_updates=["message"])


if __name__ == "__main__":
    main()
