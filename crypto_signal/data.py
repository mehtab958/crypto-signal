"""OHLCV loading: CSV files or Binance's public market-data API (no key needed).

PAXGUSDT is a token backed 1:1 by a troy ounce of gold, so it tracks XAU/USD
closely and gives free 24/7 gold candles. For broker XAUUSD data, export a CSV.
"""

import json
import time
import urllib.request

import pandas as pd

SYMBOLS = {"btc": "BTCUSDT", "gold": "PAXGUSDT"}
BASE = "https://data-api.binance.vision/api/v3/klines"


def load_csv(path: str) -> pd.DataFrame:
    """CSV with a time column (time/date/datetime/timestamp) plus open, high, low, close."""
    df = pd.read_csv(path)
    df.columns = [c.strip().lower() for c in df.columns]
    tcol = next(c for c in ("time", "datetime", "date", "timestamp") if c in df.columns)
    df.index = pd.to_datetime(df.pop(tcol), utc=True)
    return df[["open", "high", "low", "close"] + (["volume"] if "volume" in df else [])].astype(float).sort_index()


def fetch_binance(asset: str, interval: str = "1h", bars: int = 5000) -> pd.DataFrame:
    symbol = SYMBOLS.get(asset, asset.upper())
    rows, end = [], None
    while len(rows) < bars:
        url = f"{BASE}?symbol={symbol}&interval={interval}&limit=1000" + (f"&endTime={end}" if end else "")
        with urllib.request.urlopen(url, timeout=20) as r:
            batch = json.load(r)
        if not batch:
            break
        rows = batch + rows
        end = batch[0][0] - 1
        time.sleep(0.2)
    rows = rows[-bars:]
    df = pd.DataFrame([r[:6] for r in rows], columns=["time", "open", "high", "low", "close", "volume"])
    df.index = pd.to_datetime(df.pop("time"), unit="ms", utc=True)
    return df.astype(float)
