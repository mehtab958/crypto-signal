"""Alert delivery: console always, Telegram when configured."""

from __future__ import annotations

import html
import logging
import re

from .http import HttpClient
from .scoring import Signal

log = logging.getLogger(__name__)


def money(x: float | None) -> str:
    if x is None:
        return "n/a"
    if x >= 1_000_000:
        return f"${x / 1_000_000:.2f}M"
    if x >= 1_000:
        return f"${x / 1_000:.1f}K"
    return f"${x:,.0f}"


def _age(hours: float) -> str:
    return f"{hours * 60:.0f}m" if hours < 1 else f"{hours:.1f}h"


def format_signal(sig: Signal) -> str:
    p = sig.pair
    e = html.escape
    tier = "🔥 STRONG" if sig.score >= 75 else "⚡ SIGNAL" if sig.score >= 60 else "👀 WATCH"
    lines = [
        f"<b>{tier} {sig.score:.0f}/100 — ${e(p.symbol)}</b> ({e(p.name)})",
        f"{e(p.chain)} · {e(p.dex)} · age {_age(p.age_hours)}",
        f"MC {money(p.market_cap)} · Liq {money(p.liquidity_usd)} · Vol1h {money(p.volume.get('h1'))}",
        f"Δ 5m {p.price_change.get('m5', 0):+.1f}% · 1h {p.price_change.get('h1', 0):+.1f}%"
        f" · Buys/Sells 5m {p.buys.get('m5', 0)}/{p.sells.get('m5', 0)}",
        "",
    ]
    lines += [f"✅ {e(r)}" for r in sig.reasons]
    lines += [f"⚠️ {e(w)}" for w in sig.warnings[:6]]
    parts = " ".join(f"{k[:3]} {v:.0f}" for k, v in sig.parts.items())
    lines += ["", f"<i>{parts}</i>", f"<code>{e(p.token_address)}</code>", f'<a href="{e(p.url)}">DexScreener</a>']
    if p.chain == "solana":
        lines[-1] += f' · <a href="https://rugcheck.xyz/tokens/{e(p.token_address)}">RugCheck</a>'
    lines.append("<i>Not financial advice. Most new tokens go to zero — size small, use stops.</i>")
    return "\n".join(lines)


class Alerter:
    def __init__(self, http: HttpClient, bot_token: str = "", chat_id: str = ""):
        self.http = http
        self.bot_token = bot_token
        self.chat_id = chat_id

    @property
    def telegram_enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    def send(self, text_html: str) -> None:
        plain = html.unescape(_strip_tags(text_html))
        print("\n" + "=" * 60 + "\n" + plain + "\n" + "=" * 60, flush=True)
        if not self.telegram_enabled:
            return
        try:
            self.http.post(f"https://api.telegram.org/bot{self.bot_token}/sendMessage", json={
                "chat_id": self.chat_id, "text": text_html, "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
        except Exception as exc:
            log.warning("telegram send failed: %s", exc)

    def signal(self, sig: Signal) -> None:
        self.send(format_signal(sig))


def _strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)
