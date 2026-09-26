# Scalp Confluence Pro (TradingView)

A TradingView strategy script for forex and gold scalping. It gives BUY/SELL signals with a stop-loss and two
targets, shows a "give signal" panel, sends phone alerts, and backtests itself so you can see its real win rate.

## How it decides

| Layer | What it uses | Purpose |
|---|---|---|
| Trend vote (max score 7.5) | EMA 50/200 (2.0), 15-minute EMA 50 (1.5), Supertrend (1.5), ADX + DI (1.0), MACD histogram (1.0), VWAP (0.5) | Only trade with the trend |
| Triggers (need at least one) | RSI(7) pullback, EMA-21 pullback, Bollinger re-entry, Donchian breakout | Time the entry |
| Safety | London 07:00-11:00 and New York 12:30-16:00 UTC; skip dead markets and news spikes (ATR filter); cooldown; max 6 trades a day; stop for the day after -3R | Avoid bad conditions |
| Exits | Stop 1.5 x ATR; half at 1R, rest at 2R; stop to breakeven after target 1; 24-bar time stop | Manage the trade |
| Size | 1% of equity at risk per trade | Survive losing streaks |

A signal needs a trigger **and** a score of at least +5 (buy) or -5 (sell). The higher-timeframe value uses the last
closed 15-minute bar, so signals do not repaint.

## Set up on iPhone (free)

1. Open **tradingview.com** in Safari. Tap **aA → Request Desktop Website** and sign in (free account).
2. Open a chart (e.g. `EURUSD` or `XAUUSD`, 5-minute) and tap **Pine Editor** at the bottom.
3. Delete the sample code, paste all of `scalp_confluence_pro.pine`, tap **Save**, then **Add to chart**.
4. Open the **Strategy Tester** tab: it shows win rate, profit factor, drawdown and every trade.
5. **Alerts:** tap the alarm icon, set Condition to "Scalp Confluence Pro" and "alert() function calls only",
   and turn on app notifications. Install the TradingView iPhone app to receive them. The free plan limits how
   many alerts you can have.
6. The script is saved to your account, so it also appears in the TradingView iPhone app.

## Before trading real money

- Check the Strategy Tester on **your** pair and timeframe. Set slippage/commission to match your broker's spread.
- A higher win rate is easy to get by lowering the targets (Target 1/2 inputs). Judge the result by **profit factor
  above 1.2 and an acceptable drawdown**, not by win rate alone.
- Paper-trade on a demo account for at least 2-4 weeks and compare with the backtest.
- Avoid major news (NFP, CPI, central bank decisions). The ATR spike filter helps but is not a news calendar.

Not financial advice. No indicator combination guarantees profit.
