# crypto-signal

A multi-strategy **confluence** signal engine and backtester for **Gold (XAU)** and **Bitcoin (BTC)**.
It combines the well-known strategies into one score and includes a backtester that
reports the win rate and expectancy you would actually get.

## How it works

Every bar, each strategy votes long (+1), short (-1) or neutral (0).

| Kind | Strategy | Idea |
|---|---|---|
| Filter (weight 2.0) | EMA 50/200 trend | Only trade with the major trend |
| Filter (1.0) | EMA-200 slope | Higher-timeframe direction |
| Filter (1.5) | Supertrend (10, 3) | Volatility-adjusted trend |
| Filter (1.0) | MACD histogram | Momentum is building |
| Filter (1.0) | ADX > 20 + DI | Trend is strong enough to trade |
| Trigger | RSI pullback | Buy the dip / sell the rally within the trend |
| Trigger | Bollinger re-entry | Failed extension snaps back |
| Trigger | Donchian 20 breakout | Turtle-style breakout |
| Trigger | EMA-21 pullback | Price tags the fast EMA and rejects it |

A trade opens only when **a trigger fires** *and* the weighted filter score is at least
`min_score` (5.0 out of 6.5 by default). Extra guards: skip the top 5% of volatility,
a 200-bar warm-up, and, for gold, only take entries during London and New York hours (07–20 UTC).
Stops and targets are set in multiples of ATR.

Profiles: `gold`, `gold_high_winrate`, `btc`, `btc_high_winrate` (see `crypto_signal/confluence.py`).

## Usage

```bash
pip install -r requirements.txt

python -m crypto_signal signal   --asset gold                 # latest signal: BUY / SELL / NO TRADE with stop and target
python -m crypto_signal backtest --asset btc --bars 10000     # backtest on Binance 1h candles
python -m crypto_signal backtest --csv xauusd_1h.csv --profile gold --trades
python -m crypto_signal.sweep    --asset gold                 # win rate vs. expectancy trade-off
pytest
```

Gold data comes from `PAXGUSDT` (a token backed by gold that tracks XAU/USD closely). For your broker's
XAUUSD feed, export a CSV with `time,open,high,low,close` columns.

## Results and the truth about win rate

Backtest on real 1h candles, Aug 2025 to Sep 2026 (10,000 bars). Results are in R, where 1R is the amount risked per trade, and include fees.

| Profile | Trades | Win rate | Expectancy | Profit factor |
|---|---|---|---|---|
| gold | 178 | 39.9% | +0.05R | 1.08 |
| gold_high_winrate | 189 | 58.2% | +0.02R | 1.06 |
| btc | 200 | 38.0% | -0.02R | 0.96 |
| btc_high_winrate | 248 | 57.3% | -0.08R | 0.82 |

`python -m crypto_signal.sweep` makes the key point. **You can get any win rate you want by moving
the target closer and the stop further away.** For gold:

| Stop (ATR) | Target (ATR) | Win rate | Expectancy |
|---|---|---|---|
| 1.5 | 3.0 | 38.8% | +0.08R |
| 3.0 | 0.75 | **85.0%** | +0.02R |
| 4.0 | 0.5 | **88.9%** | -0.01R |
| 6.0 | 0.4 | **92.1%** | -0.00R |

An 85–90% win rate is easy to reach, and on its own it means nothing. Each of those rare losses
wipes out 5–10 wins. What matters is **expectancy**: win% × average win − loss% × average loss.
Combining more indicators doesn't add up their "win rates" either: they mostly measure the same
price movement, so extra filters mainly reduce the number of trades.

Anyone selling an 85–90%-win-rate system either uses this tiny-target trick, shows cherry-picked
backtests, or leaves out losing periods. Use this tool to test ideas out-of-sample, keep the risk per trade
small (0.5–1% of the account), and paper-trade before using real money. This is not financial advice.
