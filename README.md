# crypto-signal

## Institutional Confluence Scalper (TradingView, Pine Script v6)

File: [`strategies/institutional_confluence_scalper.pine`](strategies/institutional_confluence_scalper.pine)

### How to load it
1. TradingView → **Pine Editor** → *New* → *Blank strategy*, paste the file, **Save**, **Add to chart**.
2. Suggested chart: 1m–5m for scalping (BTC, ETH, XAUUSD, EURUSD, NAS100). Keep **HTF timeframe** at 15–60.
3. Open **Strategy Tester** to see the results. Tune the settings per symbol.
4. Alerts: *Create alert* → condition = this strategy → **"alert() function calls only"**. The message is JSON (side, entry, sl, tp1, tp2, score), so it can go straight to a webhook or bot.

### What each school of thought contributes

| Concept | How it is coded |
|---|---|
| **ICT**: liquidity sweep / stop hunt | A wick through a swing high/low, previous-day H/L or the Asian range, with the candle closing back inside |
| **ICT / SMC**: MSS / CHoCH + displacement | A large-bodied candle (≥ 0.8 × ATR) closes through the last opposite swing |
| **ICT**: Fair Value Gap, CE (50 %) entry | Limit order at the midpoint of the FVG left by the displacement |
| **ICT**: premium / discount, OTE | Scores +1 when the entry is in the discount half (longs) or premium half (shorts) of the sweep→MSS range |
| **ICT**: killzones | London 02:00–05:00 and NY 07:00–10:00 (New York time); NY PM is optional |
| **MMXM** (Market Maker model) | The full sequence: Asia range → Judas sweep → MSS → FVG → run to opposite liquidity |
| **Institutional / "bank" strategy** | Previous-day and Asian-range liquidity pools, session VWAP side, volume spike on displacement, HTF 200-EMA bias |
| **Raja Banks-style trend + key levels** | Only trades with the HTF trend, only at key levels, and needs a strong momentum candle for confirmation |
| **MMI** (Market Meanness Index) | Scores +1 when smoothed MMI is falling, meaning the market is trending rather than chopping |
| **Fundamentals** | Optional DXY intermarket filter, manual CPI/NFP/FOMC blackout windows, an abnormal-volatility guard, and no new trades on Friday afternoon |

### Risk model
* The stop sits beyond the sweep wick plus an ATR buffer. Setups whose stop is too tight or too wide are skipped.
* **TP1 = 3R** (50 % closed), **TP2 = 5R** (runner), and the stop moves to break-even after TP1.
* Each trade risks a fixed % of equity, capped by the max-leverage setting, with a daily cap on trades.

### Honest expectations
* 1:3–1:5 is a **reward-to-risk** ratio, not a win rate. At 3R the break-even win rate is about 25 %. A realistic result for this kind of model is roughly 30–45 % winners, and that is still profitable at these targets. The dashboard shows your win rate next to the break-even rate.
* No strategy wins all the time. Backtest each symbol, include real commission and slippage, and forward-test on paper before using real money.
* Pine Script cannot read a live economic calendar. The "fundamentals" here are macro and volatility proxies plus news windows you set yourself.
