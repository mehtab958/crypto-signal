"""DexScreener public API wrapper (https://docs.dexscreener.com/api/reference)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Iterable

from .http import HttpClient

BASE = "https://api.dexscreener.com"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass
class Pair:
    chain: str
    dex: str
    pair_address: str
    token_address: str
    symbol: str
    name: str
    url: str
    price_usd: float
    liquidity_usd: float | None  # None for bonding-curve pairs (pump.fun etc.)
    market_cap: float
    fdv: float
    created_at_ms: int
    buys: dict[str, int]
    sells: dict[str, int]
    volume: dict[str, float]
    price_change: dict[str, float]
    websites: list[str] = field(default_factory=list)
    socials: dict[str, str] = field(default_factory=dict)  # type -> url
    boosts: int = 0

    @classmethod
    def from_api(cls, d: dict[str, Any]) -> "Pair":
        info = d.get("info") or {}
        liq = (d.get("liquidity") or {}).get("usd")
        txns = d.get("txns") or {}
        socials: dict[str, str] = {}
        for s in info.get("socials") or []:
            if s.get("type") and s.get("url"):
                socials.setdefault(s["type"].lower(), s["url"])
        return cls(
            chain=d.get("chainId", ""),
            dex=d.get("dexId", ""),
            pair_address=d.get("pairAddress", ""),
            token_address=(d.get("baseToken") or {}).get("address", ""),
            symbol=(d.get("baseToken") or {}).get("symbol", "?"),
            name=(d.get("baseToken") or {}).get("name", "?"),
            url=d.get("url", ""),
            price_usd=_f(d.get("priceUsd")),
            liquidity_usd=_f(liq) if liq is not None else None,
            market_cap=_f(d.get("marketCap") or d.get("fdv")),
            fdv=_f(d.get("fdv")),
            created_at_ms=int(d.get("pairCreatedAt") or 0),
            buys={k: int((v or {}).get("buys", 0)) for k, v in txns.items()},
            sells={k: int((v or {}).get("sells", 0)) for k, v in txns.items()},
            volume={k: _f(v) for k, v in (d.get("volume") or {}).items()},
            price_change={k: _f(v) for k, v in (d.get("priceChange") or {}).items()},
            websites=[w["url"] for w in info.get("websites") or [] if w.get("url")],
            socials=socials,
            boosts=int((d.get("boosts") or {}).get("active", 0)),
        )

    @property
    def age_hours(self) -> float:
        if not self.created_at_ms:
            return float("inf")
        return max(0.0, (time.time() * 1000 - self.created_at_ms) / 3_600_000)

    @property
    def is_bonding_curve(self) -> bool:
        return self.liquidity_usd is None

    def txns(self, window: str) -> int:
        return self.buys.get(window, 0) + self.sells.get(window, 0)


class DexScreener:
    def __init__(self, http: HttpClient):
        self.http = http

    def _list(self, path: str) -> list[dict]:
        data = self.http.get(f"{BASE}{path}")
        if isinstance(data, dict):  # some endpoints wrap results
            data = data.get("pairs") or data.get("data") or [data]
        return data or []

    def latest_profiles(self) -> list[dict]:
        """Newest tokens that just created a DexScreener profile (usually minutes after launch)."""
        return self._list("/token-profiles/latest/v1")

    def latest_boosts(self) -> list[dict]:
        return self._list("/token-boosts/latest/v1")

    def top_boosts(self) -> list[dict]:
        return self._list("/token-boosts/top/v1")

    def discover(self, chains: Iterable[str]) -> list[tuple[str, str]]:
        """Return unique (chain, token_address) candidates from the new-token feeds."""
        wanted = set(chains)
        seen: dict[tuple[str, str], None] = {}
        for feed in (self.latest_profiles, self.latest_boosts, self.top_boosts):
            try:
                items = feed()
            except Exception:  # one feed failing shouldn't kill discovery
                continue
            for item in items:
                chain, addr = item.get("chainId"), item.get("tokenAddress")
                if chain in wanted and addr:
                    seen.setdefault((chain, addr), None)
        return list(seen)

    def pairs_for_tokens(self, chain: str, addresses: list[str]) -> dict[str, Pair]:
        """Best (most liquid / most traded) pair per token, batched 30 per request."""
        best: dict[str, Pair] = {}
        for i in range(0, len(addresses), 30):
            batch = addresses[i:i + 30]
            by_lower = {a.lower(): a for a in batch}  # EVM addresses may differ in checksum case
            for raw in self._list(f"/tokens/v1/{chain}/{','.join(batch)}"):
                pair = Pair.from_api(raw)
                key = by_lower.get(pair.token_address.lower())
                if key is None:  # token is the quote side of this pair; skip
                    continue
                current = best.get(key)
                if current is None or _pair_rank(pair) > _pair_rank(current):
                    best[key] = pair
        return best


def best_pair_any_chain(dex: "DexScreener", address: str) -> Pair | None:
    """Look a token up without knowing its chain (DexScreener searches every chain)."""
    data = dex.http.get(f"{BASE}/latest/dex/tokens/{address}") or {}
    pairs = [Pair.from_api(p) for p in data.get("pairs") or []]
    pairs = [p for p in pairs if p.token_address.lower() == address.lower()]
    return max(pairs, key=_pair_rank) if pairs else None


def _pair_rank(p: Pair) -> tuple[bool, float]:
    # Prefer real AMM pools over bonding curves: once a pump.fun token graduates, the curve pair is dead.
    return (not p.is_bonding_curve, (p.liquidity_usd or 0) + p.volume.get("h1", 0))
