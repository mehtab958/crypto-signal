"""SQLite persistence: sent signals, whale trades, wallet cursors and signal outcomes."""

from __future__ import annotations

import json
import sqlite3
import time

from .scoring import Signal
from .whales import WhaleTrade

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain TEXT NOT NULL,
    token TEXT NOT NULL,
    symbol TEXT,
    pair_url TEXT,
    score REAL,
    parts TEXT,
    price_usd REAL,
    market_cap REAL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS signals_token ON signals(chain, token, created_at);

CREATE TABLE IF NOT EXISTS outcomes (
    signal_id INTEGER NOT NULL,
    minutes INTEGER NOT NULL,
    price_usd REAL,
    multiple REAL,
    checked_at INTEGER,
    PRIMARY KEY (signal_id, minutes)
);

CREATE TABLE IF NOT EXISTS whale_trades (
    tx TEXT NOT NULL,
    token TEXT NOT NULL,
    wallet TEXT NOT NULL,
    wallet_label TEXT,
    weight REAL,
    chain TEXT,
    side TEXT,
    amount REAL,
    quote_amount REAL,
    timestamp INTEGER,
    PRIMARY KEY (tx, token, wallet)
);
CREATE INDEX IF NOT EXISTS whale_trades_token ON whale_trades(chain, token, timestamp);

CREATE TABLE IF NOT EXISTS cursors (
    wallet TEXT PRIMARY KEY,
    value TEXT
);
"""


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    # --- cursors -----------------------------------------------------------------------------
    def get_cursor(self, wallet: str) -> str | None:
        row = self.db.execute("SELECT value FROM cursors WHERE wallet=?", (wallet,)).fetchone()
        return row["value"] if row else None

    def set_cursor(self, wallet: str, value) -> None:
        if value is None:
            return
        self.db.execute("INSERT INTO cursors(wallet, value) VALUES(?, ?) "
                        "ON CONFLICT(wallet) DO UPDATE SET value=excluded.value", (wallet, str(value)))
        self.db.commit()

    # --- whale trades --------------------------------------------------------------------------
    def add_whale_trades(self, trades: list[WhaleTrade]) -> list[WhaleTrade]:
        """Insert trades, returning only the ones not seen before."""
        new = []
        for t in trades:
            cur = self.db.execute(
                "INSERT OR IGNORE INTO whale_trades VALUES (?,?,?,?,?,?,?,?,?,?)",
                (t.tx, t.token, t.wallet, t.wallet_label, t.weight, t.chain, t.side, t.amount, t.quote_amount,
                 t.timestamp))
            if cur.rowcount:
                new.append(t)
        self.db.commit()
        return new

    def recent_whale_buys(self, chain: str, token: str, since_ts: int) -> list[WhaleTrade]:
        rows = self.db.execute(
            "SELECT * FROM whale_trades WHERE chain=? AND lower(token)=lower(?) AND side='buy' AND timestamp>=?",
            (chain, token, since_ts)).fetchall()
        return [WhaleTrade(wallet=r["wallet"], wallet_label=r["wallet_label"], weight=r["weight"], chain=r["chain"],
                           token=r["token"], side=r["side"], amount=r["amount"], quote_amount=r["quote_amount"],
                           timestamp=r["timestamp"], tx=r["tx"]) for r in rows]

    # --- signals -------------------------------------------------------------------------------
    def last_signal(self, chain: str, token: str):
        return self.db.execute(
            "SELECT * FROM signals WHERE chain=? AND token=? ORDER BY created_at DESC LIMIT 1",
            (chain, token)).fetchone()

    def should_alert(self, chain: str, token: str, score: float, new_whale: bool,
                     cooldown_s: int = 6 * 3600, rescore_jump: float = 15) -> bool:
        """Alert once per token, unless a new whale buys or the score jumps a lot after the cooldown."""
        last = self.last_signal(chain, token)
        if last is None or new_whale:
            return True
        return time.time() - last["created_at"] > cooldown_s and score >= last["score"] + rescore_jump

    def add_signal(self, sig: Signal) -> int:
        p = sig.pair
        cur = self.db.execute(
            "INSERT INTO signals(chain, token, symbol, pair_url, score, parts, price_usd, market_cap, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (p.chain, p.token_address, p.symbol, p.url, sig.score, json.dumps(sig.parts), p.price_usd,
             p.market_cap, int(time.time())))
        self.db.commit()
        return int(cur.lastrowid)

    # --- performance tracking ------------------------------------------------------------------
    def due_outcomes(self, checkpoints: list[int]) -> list[tuple[sqlite3.Row, int]]:
        now = int(time.time())
        due = []
        for minutes in checkpoints:
            rows = self.db.execute(
                "SELECT s.* FROM signals s LEFT JOIN outcomes o ON o.signal_id=s.id AND o.minutes=? "
                "WHERE o.signal_id IS NULL AND s.created_at <= ?", (minutes, now - minutes * 60)).fetchall()
            due.extend((r, minutes) for r in rows)
        return due

    def add_outcome(self, signal_id: int, minutes: int, price: float, entry: float) -> None:
        multiple = price / entry if entry else 0
        self.db.execute("INSERT OR REPLACE INTO outcomes VALUES (?,?,?,?,?)",
                        (signal_id, minutes, price, multiple, int(time.time())))
        self.db.commit()

    def performance(self) -> list[dict]:
        rows = self.db.execute(
            "SELECT minutes, COUNT(*) n, AVG(multiple) avg_mult, "
            "SUM(multiple >= 2) x2, SUM(multiple >= 1.2) up20, SUM(multiple <= 0.5) down50, "
            "MAX(multiple) best FROM outcomes GROUP BY minutes ORDER BY minutes").fetchall()
        return [dict(r) for r in rows]

    def recent_signals(self, limit: int = 20) -> list[dict]:
        rows = self.db.execute(
            "SELECT s.id, s.chain, s.symbol, s.score, s.price_usd, s.created_at, "
            "(SELECT group_concat(o.minutes || 'm:' || printf('%.2fx', o.multiple), ' ') FROM outcomes o "
            " WHERE o.signal_id=s.id) AS results FROM signals s ORDER BY s.created_at DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]

