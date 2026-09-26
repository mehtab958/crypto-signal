"""Configuration loading: YAML file for settings, environment variables for secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Filters:
    min_liquidity_usd: float = 8_000
    max_liquidity_usd: float = 2_000_000
    min_market_cap_usd: float = 10_000
    max_market_cap_usd: float = 5_000_000
    max_age_hours: float = 24
    min_txns_h1: int = 30
    max_price_change_h1: float = 400


@dataclass
class Scoring:
    alert_threshold: float = 60
    whale_alert_always: bool = True


@dataclass
class Safety:
    require_safety_check: bool = True
    max_top10_holder_pct: float = 45
    max_tax_pct: float = 10
    max_rugcheck_normalised: float = 30


@dataclass
class Whale:
    address: str
    chain: str = "solana"
    label: str = ""
    weight: float = 1.0

    @property
    def name(self) -> str:
        return self.label or f"{self.address[:4]}…{self.address[-4:]}"


@dataclass
class Whales:
    lookback_minutes: float = 30
    wallets: list[Whale] = field(default_factory=list)


@dataclass
class Socials:
    check_telegram_members: bool = True
    check_website: bool = True


@dataclass
class Tracker:
    checkpoints_minutes: list[int] = field(default_factory=lambda: [15, 60, 240, 1440])


@dataclass
class Secrets:
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    solana_rpc_url: str = "https://api.mainnet-beta.solana.com"
    etherscan_api_key: str = ""


@dataclass
class Config:
    chains: list[str] = field(default_factory=lambda: ["solana", "base", "bsc", "ethereum"])
    scan_interval_seconds: float = 60
    filters: Filters = field(default_factory=Filters)
    scoring: Scoring = field(default_factory=Scoring)
    safety: Safety = field(default_factory=Safety)
    whales: Whales = field(default_factory=Whales)
    socials: Socials = field(default_factory=Socials)
    tracker: Tracker = field(default_factory=Tracker)
    database_path: str = "whalebot.db"
    secrets: Secrets = field(default_factory=Secrets)


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader so we don't need python-dotenv. Existing env vars win."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _section(cls, data: dict[str, Any] | None):
    data = data or {}
    known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
    return cls(**known)


def load_config(path: str | os.PathLike | None = "config.yaml", env_file: str = ".env") -> Config:
    _load_dotenv(Path(env_file))
    raw: dict[str, Any] = {}
    if path and Path(path).exists():
        raw = yaml.safe_load(Path(path).read_text()) or {}

    whales_raw = raw.get("whales") or {}
    wallets: list[Whale] = []
    for w in whales_raw.get("solana") or []:
        wallets.append(Whale(address=w["address"], chain="solana",
                             label=w.get("label", ""), weight=float(w.get("weight", 1.0))))
    for w in whales_raw.get("evm") or []:
        wallets.append(Whale(address=w["address"].lower(), chain=w.get("chain", "ethereum"),
                             label=w.get("label", ""), weight=float(w.get("weight", 1.0))))

    cfg = Config(
        chains=raw.get("chains") or Config().chains,
        scan_interval_seconds=float(raw.get("scan_interval_seconds", 60)),
        filters=_section(Filters, raw.get("filters")),
        scoring=_section(Scoring, raw.get("scoring")),
        safety=_section(Safety, raw.get("safety")),
        whales=Whales(lookback_minutes=float(whales_raw.get("lookback_minutes", 30)), wallets=wallets),
        socials=_section(Socials, raw.get("socials")),
        tracker=_section(Tracker, raw.get("tracker")),
        database_path=raw.get("database_path", "whalebot.db"),
        secrets=Secrets(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", ""),
            solana_rpc_url=os.getenv("SOLANA_RPC_URL") or Secrets.solana_rpc_url,
            etherscan_api_key=os.getenv("ETHERSCAN_API_KEY", ""),
        ),
    )
    return cfg
