from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


def load_csv(symbol: str = "BTCUSD", timeframe: str = "4h", start=None, end=None) -> pd.DataFrame:
    """Load bundled historical candles (Bitstamp BTC/USD, resampled from 1-minute data)."""
    df = pd.read_csv(DATA_DIR / f"{symbol}_{timeframe}.csv.gz", index_col="time", parse_dates=True)
    if start:
        df = df[df.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        df = df[df.index < pd.Timestamp(end, tz="UTC")]
    return df


def fetch_ohlcv(exchange, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
    """Fetch recent candles from a ccxt exchange and drop the still-forming last candle."""
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["time", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["time"], unit="ms", utc=True)
    df = df.set_index("time").astype(float)
    tf_ms = exchange.parse_timeframe(timeframe) * 1000
    now_ms = exchange.milliseconds()
    if len(df) and df.index[-1].value // 10**6 + tf_ms > now_ms:
        df = df.iloc[:-1]
    return df
