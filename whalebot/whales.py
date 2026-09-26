"""Whale / smart-money wallet tracking.

Solana: any JSON-RPC endpoint (public mainnet works but is slow and rate-limited; Helius/QuickNode recommended).
EVM:    Etherscan V2 multichain API (one free key covers Ethereum, BSC, Base, Arbitrum, Polygon, ...).

A "buy" is a positive token balance change for the wallet in a transaction the wallet itself signed/sent,
which filters out airdropped spam tokens that scammers push into well-known whale wallets.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .config import Whale
from .http import HttpClient
from .safety import EVM_CHAIN_IDS

log = logging.getLogger(__name__)

# Quote / base assets a whale spends to buy memecoins. Changes in these are never "buys".
SOLANA_QUOTE_MINTS = {
    "So11111111111111111111111111111111111111112",   # wSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
}
EVM_QUOTE_SYMBOLS = {"WETH", "ETH", "USDC", "USDT", "DAI", "WBNB", "BNB", "USDBC", "USDC.E", "WMATIC", "WPOL",
                     "FDUSD", "BUSD", "CBBTC", "WBTC"}

LAMPORTS = 1_000_000_000


@dataclass
class WhaleTrade:
    wallet: str
    wallet_label: str
    weight: float
    chain: str
    token: str
    side: str            # "buy" | "sell"
    amount: float        # token units
    quote_amount: float  # SOL spent for Solana buys, 0 if unknown
    timestamp: int
    tx: str


def token_deltas(tx: dict, owner: str) -> dict[str, float]:
    """Net token balance change per mint for `owner` in a jsonParsed Solana transaction."""
    meta = tx.get("meta") or {}
    deltas: dict[str, float] = {}
    for sign, key in ((-1, "preTokenBalances"), (1, "postTokenBalances")):
        for b in meta.get(key) or []:
            if b.get("owner") != owner:
                continue
            amt = float((b.get("uiTokenAmount") or {}).get("uiAmount") or 0)
            deltas[b["mint"]] = deltas.get(b["mint"], 0.0) + sign * amt
    return {m: d for m, d in deltas.items() if abs(d) > 0}


def sol_delta(tx: dict, owner: str) -> float:
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    meta = tx.get("meta") or {}
    for i, k in enumerate(keys):
        pubkey = k.get("pubkey") if isinstance(k, dict) else k
        if pubkey == owner:
            try:
                return (meta["postBalances"][i] - meta["preBalances"][i]) / LAMPORTS
            except (KeyError, IndexError):
                return 0.0
    return 0.0


def signer_of(tx: dict) -> str | None:
    keys = ((tx.get("transaction") or {}).get("message") or {}).get("accountKeys") or []
    for k in keys:
        if isinstance(k, dict) and k.get("signer"):
            return k.get("pubkey")
    return None


def parse_solana_tx(tx: dict, whale: Whale, signature: str) -> list[WhaleTrade]:
    if not tx or (tx.get("meta") or {}).get("err"):
        return []
    signer = signer_of(tx)
    if signer and signer != whale.address:
        return []  # someone else's tx that touched this wallet (airdrop, transfer in)
    trades = []
    sol = sol_delta(tx, whale.address)
    wsol = token_deltas(tx, whale.address).get("So11111111111111111111111111111111111111112", 0.0)
    for mint, delta in token_deltas(tx, whale.address).items():
        if mint in SOLANA_QUOTE_MINTS:
            continue
        side = "buy" if delta > 0 else "sell"
        spent = -(sol + wsol) if side == "buy" else 0.0
        trades.append(WhaleTrade(
            wallet=whale.address, wallet_label=whale.name, weight=whale.weight, chain="solana", token=mint,
            side=side, amount=abs(delta), quote_amount=max(0.0, spent),
            timestamp=int(tx.get("blockTime") or time.time()), tx=signature,
        ))
    return trades


class SolanaTracker:
    def __init__(self, http: HttpClient, rpc_url: str):
        self.http = http
        self.rpc_url = rpc_url

    def _rpc(self, method: str, params: list):
        data = self.http.post(self.rpc_url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
        if data and data.get("error"):
            raise RuntimeError(f"{method}: {data['error']}")
        return (data or {}).get("result")

    def poll(self, whale: Whale, since_sig: str | None, min_ts: int, limit: int = 25) -> tuple[list[WhaleTrade], str | None]:
        opts: dict = {"limit": limit}
        if since_sig:
            opts["until"] = since_sig
        sigs = self._rpc("getSignaturesForAddress", [whale.address, opts]) or []
        newest = sigs[0]["signature"] if sigs else since_sig
        trades: list[WhaleTrade] = []
        for s in sigs:
            if s.get("err") or (s.get("blockTime") or 0) < min_ts:
                continue
            try:
                tx = self._rpc("getTransaction", [s["signature"], {
                    "encoding": "jsonParsed", "maxSupportedTransactionVersion": 0, "commitment": "confirmed"}])
            except Exception as exc:
                log.debug("getTransaction %s failed: %s", s["signature"], exc)
                continue
            trades.extend(parse_solana_tx(tx, whale, s["signature"]))
        return trades, newest


def parse_evm_transfers(transfers: list[dict], sent_hashes: set[str], whale: Whale, chain: str,
                        min_ts: int) -> list[WhaleTrade]:
    trades = []
    addr = whale.address.lower()
    for t in transfers:
        ts = int(t.get("timeStamp") or 0)
        if ts < min_ts or (t.get("tokenSymbol") or "").upper() in EVM_QUOTE_SYMBOLS:
            continue
        if t.get("hash", "").lower() not in sent_hashes:
            continue  # wallet didn't initiate this tx -> probably an airdrop / spam
        to, frm = (t.get("to") or "").lower(), (t.get("from") or "").lower()
        if to == addr:
            side = "buy"
        elif frm == addr:
            side = "sell"
        else:
            continue
        try:
            amount = int(t.get("value") or 0) / 10 ** int(t.get("tokenDecimal") or 18)
        except ValueError:
            amount = 0.0
        trades.append(WhaleTrade(
            wallet=whale.address, wallet_label=whale.name, weight=whale.weight, chain=chain,
            token=t.get("contractAddress", "").lower(), side=side, amount=amount, quote_amount=0.0,
            timestamp=ts, tx=t.get("hash", ""),
        ))
    return trades


class EvmTracker:
    URL = "https://api.etherscan.io/v2/api"

    def __init__(self, http: HttpClient, api_key: str):
        self.http = http
        self.api_key = api_key

    def _call(self, chain_id: int, action: str, address: str, start_block: int) -> list[dict]:
        data = self.http.get(self.URL, params={
            "chainid": chain_id, "module": "account", "action": action, "address": address,
            "startblock": start_block, "endblock": 99_999_999, "page": 1, "offset": 100, "sort": "desc",
            "apikey": self.api_key,
        })
        result = (data or {}).get("result")
        return result if isinstance(result, list) else []

    def poll(self, whale: Whale, since_block: int, min_ts: int) -> tuple[list[WhaleTrade], int]:
        chain_id = EVM_CHAIN_IDS.get(whale.chain)
        if chain_id is None or not self.api_key:
            return [], since_block
        transfers = self._call(chain_id, "tokentx", whale.address, since_block)
        normal = self._call(chain_id, "txlist", whale.address, since_block)
        sent = {t["hash"].lower() for t in normal if (t.get("from") or "").lower() == whale.address.lower()}
        newest = max([int(t.get("blockNumber") or 0) for t in transfers + normal] + [since_block])
        return parse_evm_transfers(transfers, sent, whale, whale.chain, min_ts), newest
