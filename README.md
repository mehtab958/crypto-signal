# crypto-signal

TradingView (Pine Script v6) implementation of the trend-following model from
**Zarattini, Pagani & Barbon (2025), "Catching Crypto Trends; A Tactical Approach for Bitcoin and Altcoins"**
([SSRN 5209907](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5209907)).

The paper reports these results after fees for BTC from 2015: 30% CAGR, Sharpe ratio 1.56 and a maximum drawdown of about 19%. Buy-and-hold had drawdowns above 80% over the same period.

## Files

| File | Purpose |
|---|---|
| `pine/crypto_trend_ensemble.pine` | Indicator: exposure pane, stop lines, LONG/FLAT markers, status table and alerts |
| `pine/crypto_trend_ensemble_strategy.pine` | Strategy version for TradingView's Strategy Tester (0.1% commission, rebalance band) |

## Rules (use a Daily chart)

1. Nine Donchian models with lookbacks of 5, 10, 20, 30, 60, 90, 150, 250 and 360 days.
2. **Entry:** a model goes long when the close is a new n-day closing high.
3. **Exit:** each model has a trailing stop that starts at the Donchian midpoint `(highest high + lowest low) / 2` and only moves up. The model exits when the close falls below the stop.
4. **Signal:** the share of the nine models that are long (0–100%).
5. **Sizing:** `exposure = signal × min(25% / realized 90-day vol, 1.0)`. The strategy is long-only.

## How to use

1. Open TradingView and go to Pine Editor. Paste in a file, save it and add it to the chart.
2. Use the **1D** timeframe. All lookbacks are counted in bars.
3. Read the pane like this: the orange line is the ensemble signal and the green columns are the suggested exposure (percent of capital).
4. On the price chart, the orange line is where the first model would exit. The red line is where every model would be out.
5. To set up alerts, use **CTE: turned LONG**, **CTE: turned FLAT** or **CTE: signal changed**. The last one fires on every rebalance.

Signals are computed at the daily close. Trade on the next bar so live results match the backtest.
