"""Social presence checks for newly launched tokens.

Real "hype" data (X/Twitter mentions, follower growth) needs paid APIs, so this module sticks to signals
available for free: which socials a project links, whether its website is live, Telegram member counts
(via the Bot API, works for public groups/channels), and whether the team paid for DexScreener promotion.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

from .dexscreener import Pair
from .http import HttpClient

log = logging.getLogger(__name__)

_TG_RE = re.compile(r"(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z0-9_]{4,})", re.I)
_X_STATUS_RE = re.compile(r"(?:x|twitter)\.com/[^/]+/status/", re.I)


@dataclass
class SocialReport:
    score: float                     # 0..1
    has_twitter: bool = False
    has_telegram: bool = False
    has_website: bool = False
    website_live: bool | None = None
    telegram_members: int | None = None
    notes: list[str] = field(default_factory=list)


def telegram_username(url: str) -> str | None:
    m = _TG_RE.search(url or "")
    if not m or m.group(1).lower() in {"joinchat", "addlist", "share"}:
        return None  # private invite links can't be looked up
    return m.group(1)


def telegram_member_count(http: HttpClient, bot_token: str, username: str) -> int | None:
    if not bot_token:
        return None
    try:
        data = http.get(f"https://api.telegram.org/bot{bot_token}/getChatMemberCount",
                        params={"chat_id": f"@{username}"})
        return int(data["result"]) if data and data.get("ok") else None
    except Exception:
        return None


def score_socials(has_twitter: bool, has_telegram: bool, has_website: bool, website_live: bool | None,
                  tg_members: int | None, twitter_is_post: bool, boosts: int) -> tuple[float, list[str]]:
    """Pure scoring function (unit-tested)."""
    notes: list[str] = []
    score = 0.0
    if has_twitter:
        score += 0.25
        if twitter_is_post:
            # A link to a single tweet (not an account) is typical of low-effort meme launches.
            score -= 0.1
            notes.append("X link is a post, not an account")
    if has_telegram:
        score += 0.2
    if has_website:
        score += 0.15 if website_live is not False else 0.0
        if website_live is False:
            notes.append("website down")
    if tg_members is not None:
        if tg_members >= 1000:
            score += 0.25
        elif tg_members >= 300:
            score += 0.15
        elif tg_members >= 100:
            score += 0.05
        notes.append(f"TG {tg_members} members")
    if boosts:
        # Paid boosts mean the team has budget and is marketing, but also that the chart attention is bought.
        score += min(0.15, 0.03 * boosts)
        notes.append(f"{boosts} boosts")
    if not (has_twitter or has_telegram or has_website):
        notes.append("no socials")
    return max(0.0, min(1.0, score)), notes


def check(http: HttpClient, pair: Pair, bot_token: str = "", check_tg: bool = True,
          check_web: bool = True) -> SocialReport:
    twitter = pair.socials.get("twitter") or pair.socials.get("x")
    tg = pair.socials.get("telegram")
    website = pair.websites[0] if pair.websites else None

    website_live: bool | None = None
    if website and check_web:
        website_live = http.head_ok(website)

    tg_members: int | None = None
    if tg and check_tg:
        username = telegram_username(tg)
        if username:
            tg_members = telegram_member_count(http, bot_token, username)

    score, notes = score_socials(
        has_twitter=bool(twitter), has_telegram=bool(tg), has_website=bool(website),
        website_live=website_live, tg_members=tg_members,
        twitter_is_post=bool(twitter and _X_STATUS_RE.search(twitter)), boosts=pair.boosts,
    )
    return SocialReport(score=score, has_twitter=bool(twitter), has_telegram=bool(tg),
                        has_website=bool(website), website_live=website_live,
                        telegram_members=tg_members, notes=notes)
