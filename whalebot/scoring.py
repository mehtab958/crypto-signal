"""Signal scoring. Pure functions only, so the logic is easy to test and tune.

Total score is 0..100:
    momentum  up to 35  - buy pressure, volume acceleration, turnover, healthy (not parabolic) price action
    whales    up to 30  - tracked smart-money wallets buying recently (confluence of several = strongest)
    safety    up to 20  - RugCheck / GoPlus result
    social    up to 10  - socials present, TG size, website live
    early     up to 5   - younger pairs get a bonus
Hard filters reject a token outright regardless of score.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .config import Filters
from .dexscreener import Pair
from .safety import SafetyReport
from .socials import SocialReport
from .whales import WhaleTrade


@dataclass
class Signal:
    pair: Pair
    score: float
    parts: dict[str, float]
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    whale_buys: list[WhaleTrade] = field(default_factory=list)


def hard_filter(p: Pair, f: Filters) -> str | None:
    """Return a rejection reason, or None if the pair is eligible."""
    if p.price_usd <= 0:
        return "no price"
    if p.age_hours > f.max_age_hours:
        return f"too old ({p.age_hours:.1f}h)"
    if not p.is_bonding_curve:
        if p.liquidity_usd < f.min_liquidity_usd:
            return f"liquidity ${p.liquidity_usd:,.0f} too low"
        if p.liquidity_usd > f.max_liquidity_usd:
            return "liquidity too high (not early)"
    if p.market_cap and not (f.min_market_cap_usd <= p.market_cap <= f.max_market_cap_usd):
        return f"mcap ${p.market_cap:,.0f} out of range"
    if p.txns("h1") < f.min_txns_h1:
        return f"only {p.txns('h1')} txns/1h"
    if p.price_change.get("h1", 0) > f.max_price_change_h1:
        return f"already +{p.price_change['h1']:.0f}% in 1h (late)"
    if p.price_change.get("h1", 0) < -50:
        return "dumping (-50% 1h)"
    return None


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def momentum_score(p: Pair) -> tuple[float, list[str], list[str]]:
    """0..35."""
    reasons, warnings = [], []

    # Buy pressure: more buyers than sellers, recently and over the hour.
    b5, s5 = p.buys.get("m5", 0), p.sells.get("m5", 0)
    b1, s1 = p.buys.get("h1", 0), p.sells.get("h1", 0)
    ratio5 = b5 / max(1, s5)
    ratio1 = b1 / max(1, s1)
    pressure = _clamp((ratio5 - 1) / 1.5) * 0.6 + _clamp((ratio1 - 1) / 1.0) * 0.4
    if ratio5 >= 1.8 and b5 >= 10:
        reasons.append(f"buy pressure 5m {b5}/{s5}")
    if ratio5 < 0.7 and s5 >= 10:
        warnings.append(f"sellers dominating 5m ({b5}/{s5})")

    # Volume acceleration: last 5m annualised to 1h vs actual 1h volume. >1 means activity is picking up.
    v5, v1 = p.volume.get("m5", 0), p.volume.get("h1", 0)
    accel = (v5 * 12) / v1 if v1 > 0 else 0
    accel_s = _clamp((accel - 0.8) / 1.7)
    if accel >= 1.8 and v5 > 1000:
        reasons.append(f"volume accelerating {accel:.1f}x")

    # Turnover: 1h volume relative to liquidity (or mcap for bonding curves).
    base = p.liquidity_usd if p.liquidity_usd else max(p.market_cap, 1)
    turnover = v1 / base if base else 0
    turnover_s = _clamp(turnover / 3)
    if turnover >= 2:
        reasons.append(f"1h vol {turnover:.1f}x liquidity")

    # Price action: rising, but not already parabolic.
    c5, c1 = p.price_change.get("m5", 0), p.price_change.get("h1", 0)
    if c1 > 150:
        price_s = 0.3
        warnings.append(f"+{c1:.0f}% 1h, chasing risk")
    elif c5 > 0 and c1 > 0:
        price_s = _clamp(0.5 + c5 / 40)
    elif c5 > 0:
        price_s = 0.5  # bouncing
    else:
        price_s = 0.1

    total = 35 * (0.35 * pressure + 0.25 * accel_s + 0.2 * turnover_s + 0.2 * price_s)
    return round(total, 2), reasons, warnings


def whale_score(buys: list[WhaleTrade]) -> tuple[float, list[str]]:
    """0..30. One whale ~ 15, two distinct whales ~ 25, three+ = 30."""
    if not buys:
        return 0.0, []
    weight_by_wallet: dict[str, float] = {}
    labels: dict[str, str] = {}
    for t in buys:
        weight_by_wallet[t.wallet] = max(weight_by_wallet.get(t.wallet, 0), t.weight)
        labels[t.wallet] = t.wallet_label
    w = sum(weight_by_wallet.values())
    score = 30 * _clamp(1 - 0.5 ** (w * 1.0))  # 1->15, 2->22.5, 3->26.25 ...
    if len(weight_by_wallet) >= 2:
        score = min(30, score + 3)
    names = ", ".join(labels[k] for k in weight_by_wallet)
    return round(score, 2), [f"🐋 {len(weight_by_wallet)} whale(s) bought: {names}"]


def early_score(p: Pair) -> float:
    """0..5."""
    if p.age_hours < 1:
        return 5
    if p.age_hours < 3:
        return 3
    if p.age_hours < 8:
        return 1.5
    return 0


def build_signal(p: Pair, safety: SafetyReport, social: SocialReport, whale_buys: list[WhaleTrade]) -> Signal:
    m, m_reasons, m_warn = momentum_score(p)
    w, w_reasons = whale_score(whale_buys)
    s = round(20 * safety.score, 2)
    so = round(10 * social.score, 2)
    e = early_score(p)
    parts = {"momentum": m, "whales": w, "safety": s, "social": so, "early": e}
    reasons = w_reasons + m_reasons
    if social.has_twitter or social.has_telegram:
        reasons.append("socials: " + " ".join(
            x for x, on in (("X", social.has_twitter), ("TG", social.has_telegram), ("Web", social.has_website)) if on))
    warnings = m_warn + safety.flags + [n for n in social.notes if "down" in n or "no socials" in n or "post" in n]
    if p.is_bonding_curve:
        warnings.append("still on bonding curve")
    return Signal(pair=p, score=round(sum(parts.values()), 1), parts=parts, reasons=reasons,
                  warnings=warnings, whale_buys=whale_buys)
