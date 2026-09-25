"""Multi-strategy confluence signal engine for Gold (XAU) and Bitcoin (BTC)."""

from .confluence import ConfluenceEngine, PROFILES
from .backtest import backtest

__all__ = ["ConfluenceEngine", "PROFILES", "backtest"]
