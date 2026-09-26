"""Rug / honeypot checks: RugCheck for Solana, GoPlus for EVM chains."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .config import Safety as SafetyCfg
from .http import HttpClient

log = logging.getLogger(__name__)

# GoPlus / Etherscan numeric chain ids
EVM_CHAIN_IDS = {
    "ethereum": 1,
    "bsc": 56,
    "polygon": 137,
    "arbitrum": 42161,
    "base": 8453,
    "optimism": 10,
    "avalanche": 43114,
}


@dataclass
class SafetyReport:
    ok: bool                      # passes hard filters
    score: float                  # 0..1, higher = safer
    flags: list[str] = field(default_factory=list)   # human-readable warnings
    checked: bool = True          # False if the safety API was unavailable


def check_solana(http: HttpClient, mint: str, cfg: SafetyCfg) -> SafetyReport:
    try:
        data = http.get(f"https://api.rugcheck.xyz/v1/tokens/{mint}/report/summary")
    except Exception as exc:
        log.debug("rugcheck failed for %s: %s", mint, exc)
        return SafetyReport(ok=not cfg.require_safety_check, score=0.3, flags=["safety check unavailable"], checked=False)
    return evaluate_rugcheck(data or {}, cfg)


def evaluate_rugcheck(data: dict, cfg: SafetyCfg) -> SafetyReport:
    flags: list[str] = []
    ok = True
    # RugCheck's normalised score is a *risk* score: 0 = clean, higher = riskier.
    risk = float(data.get("score_normalised") or 0)
    for r in data.get("risks") or []:
        level = (r.get("level") or "").lower()
        name = r.get("name") or "risk"
        flags.append(f"{name} ({level})" if level else name)
        if level == "danger":
            ok = False
    if risk > cfg.max_rugcheck_normalised:
        ok = False
        flags.append(f"rugcheck risk {risk:.0f}")
    lp_locked = float(data.get("lpLockedPct") or 0)
    score = max(0.0, 1 - risk / 100) * (0.7 + 0.3 * min(lp_locked, 100) / 100)
    return SafetyReport(ok=ok, score=round(score, 3), flags=flags)


def check_evm(http: HttpClient, chain: str, address: str, cfg: SafetyCfg) -> SafetyReport:
    chain_id = EVM_CHAIN_IDS.get(chain)
    if chain_id is None:
        return SafetyReport(ok=not cfg.require_safety_check, score=0.3, flags=[f"no safety API for {chain}"], checked=False)
    try:
        data = http.get(f"https://api.gopluslabs.io/api/v1/token_security/{chain_id}",
                        params={"contract_addresses": address})
        result = ((data or {}).get("result") or {}).get(address.lower())
    except Exception as exc:
        log.debug("goplus failed for %s: %s", address, exc)
        result = None
    if not result:
        return SafetyReport(ok=not cfg.require_safety_check, score=0.3, flags=["safety check unavailable"], checked=False)
    return evaluate_goplus(result, cfg)


def evaluate_goplus(r: dict, cfg: SafetyCfg) -> SafetyReport:
    flags: list[str] = []
    ok = True

    def yes(key: str) -> bool:
        return str(r.get(key, "0")) == "1"

    fatal = {
        "is_honeypot": "HONEYPOT",
        "cannot_sell_all": "cannot sell all",
        "is_blacklisted": "blacklist function",
        "hidden_owner": "hidden owner",
        "can_take_back_ownership": "can take back ownership",
        "selfdestruct": "selfdestruct",
        "owner_change_balance": "owner can change balances",
    }
    warn = {
        "is_mintable": "mintable",
        "is_proxy": "proxy contract",
        "slippage_modifiable": "tax modifiable",
        "transfer_pausable": "transfers pausable",
        "trading_cooldown": "trading cooldown",
        "external_call": "external call",
    }
    penalty = 0.0
    for key, label in fatal.items():
        if yes(key):
            ok = False
            flags.append(label)
            penalty += 1
    for key, label in warn.items():
        if yes(key):
            flags.append(label)
            penalty += 0.1

    def pct(key: str) -> float:
        try:
            return float(r.get(key) or 0) * 100
        except ValueError:
            return 0.0

    buy_tax, sell_tax = pct("buy_tax"), pct("sell_tax")
    if max(buy_tax, sell_tax) > cfg.max_tax_pct:
        ok = False
        flags.append(f"tax {buy_tax:.0f}%/{sell_tax:.0f}%")

    holders = r.get("holders") or []
    top10 = sum(float(h.get("percent") or 0) for h in holders[:10]
                if not int(h.get("is_locked") or 0) and not int(h.get("is_contract") or 0)) * 100
    if top10 > cfg.max_top10_holder_pct:
        ok = False
        flags.append(f"top10 hold {top10:.0f}%")
    else:
        penalty += top10 / 200

    lp_holders = r.get("lp_holders") or []
    lp_locked = sum(float(h.get("percent") or 0) for h in lp_holders if int(h.get("is_locked") or 0)) * 100
    if lp_holders and lp_locked < 50:
        flags.append(f"LP locked {lp_locked:.0f}%")
        penalty += 0.2

    score = max(0.0, 1 - penalty)
    return SafetyReport(ok=ok, score=round(score, 3), flags=flags)


def check(http: HttpClient, chain: str, address: str, cfg: SafetyCfg) -> SafetyReport:
    if chain == "solana":
        return check_solana(http, address, cfg)
    return check_evm(http, chain, address, cfg)
