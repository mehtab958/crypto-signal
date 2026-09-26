"""Live market data from free public APIs: CoinGecko (prices, trending) and Binance (candles)."""

from __future__ import annotations

import time

import httpx

from .config import Settings
from .signals import Candle

INTERVALS = {"15m", "30m", "1h", "4h", "1d", "1w"}

# Common tickers -> CoinGecko ids, so we skip a search call for the usual suspects.
KNOWN_IDS = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "ADA": "cardano",
    "TON": "the-open-network",
    "TRX": "tron",
    "AVAX": "avalanche-2",
    "LINK": "chainlink",
    "DOT": "polkadot",
    "LTC": "litecoin",
    "SHIB": "shiba-inu",
    "PEPE": "pepe",
    "SUI": "sui",
    "ARB": "arbitrum",
    "OP": "optimism",
    "NEAR": "near",
    "MATIC": "matic-network",
    "POL": "polygon-ecosystem-token",
}


class MarketDataError(Exception):
    pass


class MarketData:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        headers = {"accept": "application/json"}
        if settings.coingecko_api_key:
            headers["x-cg-demo-api-key"] = settings.coingecko_api_key
        self._http = client or httpx.AsyncClient(timeout=15.0, headers=headers)
        self._id_cache: dict[str, str] = {}
        self._cache: dict[str, tuple[float, object]] = {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _get(self, url: str, params: dict | None = None, ttl: float = 30.0):
        key = url + "?" + "&".join(f"{k}={v}" for k, v in sorted((params or {}).items()))
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        try:
            resp = await self._http.get(url, params=params)
        except httpx.HTTPError as exc:
            raise MarketDataError(f"network error calling {url}: {exc}") from exc
        if resp.status_code == 429:
            raise MarketDataError("rate limited by market data provider, try again in a minute")
        if resp.status_code >= 400:
            raise MarketDataError(f"{url} returned HTTP {resp.status_code}: {resp.text[:200]}")
        data = resp.json()
        self._cache[key] = (time.monotonic(), data)
        return data

    # ---- CoinGecko -------------------------------------------------------

    async def resolve_id(self, symbol_or_name: str) -> str:
        q = symbol_or_name.strip()
        upper = q.upper()
        if upper in KNOWN_IDS:
            return KNOWN_IDS[upper]
        if upper in self._id_cache:
            return self._id_cache[upper]
        data = await self._get(f"{self.settings.coingecko_base_url}/search", {"query": q}, ttl=3600)
        coins = data.get("coins") or []
        if not coins:
            raise MarketDataError(f"no coin found for '{q}'")
        exact = [c for c in coins if (c.get("symbol") or "").upper() == upper]
        # CoinGecko's search is already ranked by market cap.
        coin_id = (exact or coins)[0]["id"]
        self._id_cache[upper] = coin_id
        return coin_id

    async def price(self, symbol: str) -> dict:
        coin_id = await self.resolve_id(symbol)
        data = await self._get(
            f"{self.settings.coingecko_base_url}/coins/markets",
            {"vs_currency": "usd", "ids": coin_id, "price_change_percentage": "1h,24h,7d"},
        )
        if not data:
            raise MarketDataError(f"no market data for '{symbol}'")
        c = data[0]
        return {
            "id": c["id"],
            "symbol": (c.get("symbol") or "").upper(),
            "name": c.get("name"),
            "price_usd": c.get("current_price"),
            "change_1h_pct": c.get("price_change_percentage_1h_in_currency"),
            "change_24h_pct": c.get("price_change_percentage_24h_in_currency"),
            "change_7d_pct": c.get("price_change_percentage_7d_in_currency"),
            "high_24h": c.get("high_24h"),
            "low_24h": c.get("low_24h"),
            "market_cap_usd": c.get("market_cap"),
            "market_cap_rank": c.get("market_cap_rank"),
            "volume_24h_usd": c.get("total_volume"),
            "ath_usd": c.get("ath"),
            "ath_change_pct": c.get("ath_change_percentage"),
        }

    async def overview(self) -> dict:
        base = self.settings.coingecko_base_url
        glob = (await self._get(f"{base}/global", ttl=120)).get("data", {})
        trending = await self._get(f"{base}/search/trending", ttl=300)
        top = await self._get(
            f"{base}/coins/markets",
            {"vs_currency": "usd", "order": "market_cap_desc", "per_page": 10, "page": 1,
             "price_change_percentage": "24h"},
            ttl=60,
        )
        return {
            "total_market_cap_usd": glob.get("total_market_cap", {}).get("usd"),
            "market_cap_change_24h_pct": glob.get("market_cap_change_percentage_24h_usd"),
            "btc_dominance_pct": glob.get("market_cap_percentage", {}).get("btc"),
            "eth_dominance_pct": glob.get("market_cap_percentage", {}).get("eth"),
            "top_10": [
                {"symbol": c["symbol"].upper(), "price_usd": c["current_price"],
                 "change_24h_pct": c.get("price_change_percentage_24h")}
                for c in top
            ],
            "trending": [
                {"symbol": i["item"]["symbol"], "name": i["item"]["name"],
                 "market_cap_rank": i["item"].get("market_cap_rank")}
                for i in (trending.get("coins") or [])[:7]
            ],
        }

    # ---- Binance ---------------------------------------------------------

    async def candles(self, symbol: str, interval: str = "4h", limit: int = 300) -> tuple[str, list[Candle]]:
        """Closed candles, oldest first. Tries Binance, then OKX (Binance geo-blocks some regions)."""
        if interval not in INTERVALS:
            raise MarketDataError(f"interval must be one of {sorted(INTERVALS)}")
        base, quote = split_pair(symbol)
        try:
            return base + quote, await self._binance_candles(base + quote, interval, limit)
        except MarketDataError as binance_err:
            try:
                return base + quote, await self._okx_candles(f"{base}-{quote}", interval, limit)
            except MarketDataError as okx_err:
                raise MarketDataError(
                    f"no candles for {base}{quote}. Binance: {binance_err}; OKX: {okx_err}"
                ) from okx_err

    async def _binance_candles(self, pair: str, interval: str, limit: int) -> list[Candle]:
        rows = await self._get(
            f"{self.settings.binance_base_url}/api/v3/klines",
            {"symbol": pair, "interval": interval, "limit": limit},
            ttl=20,
        )
        if not isinstance(rows, list) or not rows:
            raise MarketDataError(f"unexpected Binance response for {pair}")
        # The last row is the still-open candle; drop it so signals use closed candles only.
        return [
            Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
            for r in rows[:-1]
        ]

    async def _okx_candles(self, inst_id: str, interval: str, limit: int) -> list[Candle]:
        bar = interval if interval.endswith("m") else interval.upper()
        data = await self._get(
            f"{self.settings.okx_base_url}/api/v5/market/candles",
            {"instId": inst_id, "bar": bar, "limit": min(limit, 300)},
            ttl=20,
        )
        if data.get("code") != "0" or not data.get("data"):
            raise MarketDataError(f"OKX error for {inst_id}: {data.get('msg') or 'no data'}")
        # OKX returns newest first; field 8 is "1" once the candle has closed.
        return [
            Candle(int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5]))
            for r in reversed(data["data"])
            if r[8] == "1"
        ]


QUOTES = ("USDT", "USDC", "FDUSD", "BTC", "ETH")


def split_pair(symbol: str) -> tuple[str, str]:
    """'btc' -> ('BTC', 'USDT'); 'ETH/BTC' -> ('ETH', 'BTC'); 'SOLUSDC' -> ('SOL', 'USDC')."""
    s = symbol.upper().strip()
    for sep in ("/", "-", "_"):
        if sep in s:
            base, quote = s.split(sep, 1)
            return base, quote
    for quote in QUOTES:
        if s.endswith(quote) and len(s) > len(quote):
            return s[: -len(quote)], quote
    return s, "USDT"
