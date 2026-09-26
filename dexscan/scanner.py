"""DexScreener momentum scanner: finds tokens that are pumping *now* and flags rug-pull risk.

It measures momentum that has already happened. It cannot predict the next pump, and
most small tokens that pump later dump. Check every result before buying anything.
"""

import json
import time
import urllib.request
from collections import defaultdict
from dataclasses import dataclass, field

API = "https://api.dexscreener.com"
SOURCES = {
    "Top boosted": "/token-boosts/top/v1",
    "Latest boosted": "/token-boosts/latest/v1",
    "New profiles": "/token-profiles/latest/v1",
    "Community takeovers": "/community-takeovers/latest/v1",
}


def _get(path: str):
    req = urllib.request.Request(API + path, headers={"User-Agent": "dexscan/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def candidate_tokens(sources=tuple(SOURCES)) -> dict[str, set[str]]:
    """chainId -> token addresses gathered from the chosen DexScreener lists."""
    found = defaultdict(set)
    for name in sources:
        try:
            for item in _get(SOURCES[name]):
                if item.get("chainId") and item.get("tokenAddress"):
                    found[item["chainId"]].add(item["tokenAddress"])
        except Exception:
            continue          # one list failing should not stop the scan
    return found


def search_pairs(query: str) -> list[dict]:
    from urllib.parse import quote
    return _get(f"/latest/dex/search?q={quote(query)}").get("pairs") or []


def fetch_pairs(tokens: dict[str, set[str]]) -> list[dict]:
    """Best (most liquid) pair for each token, 30 addresses per request."""
    best = {}
    for chain, addrs in tokens.items():
        addrs = sorted(addrs)
        for i in range(0, len(addrs), 30):
            try:
                pairs = _get(f"/tokens/v1/{chain}/{','.join(addrs[i:i + 30])}")
            except Exception:
                continue
            for p in pairs:
                key = (p["chainId"], p["baseToken"]["address"])
                if key not in best or _liq(p) > _liq(best[key]):
                    best[key] = p
    return list(best.values())


def _liq(p) -> float:
    return float((p.get("liquidity") or {}).get("usd") or 0)


def _num(d, *keys) -> float:
    for k in keys:
        d = (d or {}).get(k)
    try:
        return float(d or 0)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class Result:
    symbol: str
    name: str
    chain: str
    price: float
    change_m5: float
    change_h1: float
    change_h6: float
    change_h24: float
    liquidity: float
    volume_h1: float
    fdv: float
    age_hours: float
    buy_sell_h1: float
    score: float
    verdict: str
    flags: list = field(default_factory=list)
    dexscreener: str = ""
    safety_check: str = ""


def analyse(p: dict, now_ms: float | None = None, min_liquidity: float = 20000) -> Result:
    now_ms = now_ms or time.time() * 1000
    ch = {k: _num(p, "priceChange", k) for k in ("m5", "h1", "h6", "h24")}
    liq, fdv = _liq(p), _num(p, "fdv")
    vol_h1, vol_h6 = _num(p, "volume", "h1"), _num(p, "volume", "h6")
    buys_h1, sells_h1 = _num(p, "txns", "h1", "buys"), _num(p, "txns", "h1", "sells")
    buys_m5, sells_m5 = _num(p, "txns", "m5", "buys"), _num(p, "txns", "m5", "sells")
    age_h = (now_ms - p["pairCreatedAt"]) / 3.6e6 if p.get("pairCreatedAt") else 9999
    ratio = buys_h1 / sells_h1 if sells_h1 else (buys_h1 if buys_h1 else 0)

    # Momentum score, 0-100: rising price, rising volume, more buyers than sellers, real activity.
    score = 0.0
    score += min(max(ch["m5"], 0), 20) * 1.0          # up to 20: moving right now
    score += min(max(ch["h1"], 0), 100) * 0.2         # up to 20: strong last hour
    score += 10 if ch["h6"] > 0 else 0                # trend is not just a blip
    score += min(ratio, 3) / 3 * 15                   # up to 15: buy pressure
    accel = vol_h1 / (vol_h6 / 6) if vol_h6 else 0    # last hour vs average hour
    score += min(accel, 3) / 3 * 15                   # up to 15: volume accelerating
    turnover = vol_h1 / liq if liq else 0
    score += min(turnover, 2) / 2 * 10                # up to 10: active vs pool size
    score += min(buys_h1 + sells_h1, 500) / 500 * 10  # up to 10: enough trades to be real

    flags = []
    if liq < min_liquidity:
        flags.append(f"low liquidity (${liq:,.0f})")
    if age_h < 1:
        flags.append("pair under 1 hour old")
    elif age_h < 24:
        flags.append("pair under 24 hours old")
    if liq and fdv / liq > 50:
        flags.append("valuation far above liquidity")
    if ch["h24"] < -50:
        flags.append(f"already dumped {ch['h24']:.0f}% in 24h")
    if ch["h1"] > 300 or ch["h24"] > 1000:
        flags.append("parabolic: likely late")
    if sells_m5 > buys_m5 * 1.5 and sells_m5 >= 5:
        flags.append("sellers taking over (5m)")
    if not (p.get("info") or {}).get("socials"):
        flags.append("no socials listed")
    if (p.get("boosts") or {}).get("active"):
        flags.append("paid promotion (boosted)")

    severe = {"low liquidity", "pair under 1 hour old", "already dumped", "sellers taking over"}
    n_severe = sum(any(f.startswith(s) for s in severe) for f in flags)
    if n_severe:
        verdict = "AVOID"
    elif score >= 60 and len(flags) <= 2 and not any(f.startswith("parabolic") for f in flags):
        verdict = "MOMENTUM"
    elif score >= 40:
        verdict = "WATCH"
    else:
        verdict = "WEAK"

    chain, addr = p["chainId"], p["baseToken"]["address"]
    safety = (f"https://rugcheck.xyz/tokens/{addr}" if chain == "solana"
              else f"https://honeypot.is/?address={addr}")
    return Result(p["baseToken"].get("symbol", "?"), p["baseToken"].get("name", "?"), chain,
                  _num(p, "priceUsd"), ch["m5"], ch["h1"], ch["h6"], ch["h24"], liq, vol_h1, fdv,
                  round(age_h, 1), round(ratio, 2), round(score, 1), verdict, flags,
                  p.get("url", ""), safety)


ORDER = {"MOMENTUM": 0, "WATCH": 1, "WEAK": 2, "AVOID": 3}


def scan(sources=tuple(SOURCES), query: str = "", chains=None, min_liquidity: float = 20000,
         min_volume_h1: float = 5000) -> list[Result]:
    pairs = search_pairs(query) if query else fetch_pairs(candidate_tokens(sources))
    results = [analyse(p, min_liquidity=min_liquidity) for p in pairs
               if (not chains or p["chainId"] in chains) and _num(p, "volume", "h1") >= min_volume_h1]
    return sorted(results, key=lambda r: (ORDER[r.verdict], -r.score))


if __name__ == "__main__":
    for r in scan()[:20]:
        print(f"{r.verdict:9} {r.score:5.1f}  {r.symbol:12} {r.chain:9} 1h {r.change_h1:+7.1f}%  "
              f"liq ${r.liquidity:>11,.0f}  {'; '.join(r.flags)}")
