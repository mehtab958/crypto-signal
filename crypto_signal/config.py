"""Runtime configuration, read from environment variables (and an optional .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so we don't need python-dotenv. Existing env vars win."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.split(" #", 1)[0].strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    telegram_token: str | None
    bot_name: str
    model: str
    effort: str
    default_mode: str
    history_turns: int
    enable_web_search: bool
    binance_base_url: str
    okx_base_url: str
    coingecko_base_url: str
    coingecko_api_key: str | None

    @classmethod
    def from_env(cls) -> "Settings":
        _load_dotenv(Path.cwd() / ".env")
        return cls(
            telegram_token=os.getenv("TELEGRAM_BOT_TOKEN") or None,
            bot_name=os.getenv("BOT_NAME") or "SignalBot",
            model=os.getenv("CLAUDE_MODEL") or "claude-opus-5",
            effort=os.getenv("CLAUDE_EFFORT") or "medium",
            default_mode=(os.getenv("DEFAULT_MODE") or "fun").lower(),
            history_turns=int(os.getenv("HISTORY_TURNS") or 12),
            enable_web_search=_bool(os.getenv("ENABLE_WEB_SEARCH"), True),
            binance_base_url=(os.getenv("BINANCE_BASE_URL") or "https://api.binance.com").rstrip("/"),
            okx_base_url=(os.getenv("OKX_BASE_URL") or "https://www.okx.com").rstrip("/"),
            coingecko_base_url=(os.getenv("COINGECKO_BASE_URL") or "https://api.coingecko.com/api/v3").rstrip("/"),
            coingecko_api_key=os.getenv("COINGECKO_API_KEY") or None,
        )
