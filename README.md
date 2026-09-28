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

## Raja Banks-Style Signals (TradingView indicator)

File: [`indicators/raja_banks_style_signals.pine`](indicators/raja_banks_style_signals.pine)

Trend (EMA 50/200, plus the higher-timeframe EMA 200) → price pulls back into a key support/resistance zone → an engulfing or pin-bar confirmation candle. The entry is at the candle's close. The stop sits beyond the zone plus an ATR buffer. TP1/TP2/TP3 = 2R/3R/5R, with the stop moved to break-even after TP1. The on-chart dashboard shows the win rate, TP/SL hits and net R for the last 30 days (configurable).
Raja Banks has not published an exact coded rulebook, so this follows his publicly taught principles.

## Trend Following Pro (TradingView strategy)

File: [`strategies/trend_following_pro.pine`](strategies/trend_following_pro.pine)

Trend filter (EMA 200/50 + ADX) → a breakout of the 20-bar high/low, or a pullback to the EMA 50 with a confirmation candle. Stop = 2 × ATR. TP1 = 2R (30 %), TP2 = 3R (30 %), and the runner rides a 3 × ATR trailing stop, with break-even after TP1. It exits if the trend flips. Best on 1H / 4H / Daily charts.

## Crypto Futures Pump/Dump Scanner (TradingView indicator)

File: [`indicators/futures_pump_dump_scanner.pine`](indicators/futures_pump_dump_scanner.pine)

Scans 20 Binance USDT perpetuals on every tick. A signal needs an intrabar volume explosion (≥ 3× average), a price impulse (≥ 0.6 % on one candle or ≥ 1.2 % over three), a breakout of the 30-bar high/low, and a close near the candle's high or low. A "heating" early warning appears when volume starts building. Alerts pop up with the coin name, direction, entry, SL and TP1/TP2. It catches the first seconds of a move; it cannot predict one before it starts.

## Browser Pump/Dump Scanner (all Binance USDT perpetuals)

File: [`web/pump_scanner.html`](web/pump_scanner.html). Download it and open it in Chrome or Edge, then press **Start scanner**.

It streams live 1-minute candles for every Binance USDT-M perpetual (300+ coins) over Binance's public WebSocket, with no account or API key. A PUMP/DUMP needs:
- a volume explosion (≥ 3× the 30-minute average)
- a price impulse
- a breakout of the 30-minute high/low
- taker-buy dominance
- a strong candle close

A HEATING early warning appears when volume pace builds. Each signal pops up on screen with the coin name and a sound, and shows as a desktop notification and a feed card with entry, SL and TP1/TP2. The live radar ranks the hottest coins every second. Settings are saved in your browser.

## Holistic VSA (TradingView indicator)

File: [`indicators/holistic_vsa.pine`](indicators/holistic_vsa.pine)

Volume Spread Analysis (Tom Williams / Wyckoff). Each bar is classified by volume, spread and close position, and labelled as one of these:
- **Signs of strength:** SC, SV, SO, SP, T, NS, EU
- **Signs of weakness:** BC, UT, ER, PU, ND, ED

A weighted background score over the last 20 bars decides the bias. A buy needs a No Supply, Test or Spring in a background of strength; a sell needs a No Demand or pseudo-upthrust in a background of weakness. Either one must then be confirmed by a close beyond the signal bar within 3 bars. The stop goes beyond the signal bar and TP1/2/3 = 2R/3R/5R. The dashboard shows the last 30 days of results.

## Solana Whale Tracker (browser)

File: [`web/whale_tracker.html`](web/whale_tracker.html). Open it in Chrome or Edge.

- **Whale Finder:** loads today's biggest Solana winners from DexScreener's public API. For each winner it walks back through the token's history on-chain (Solana RPC) to its first transactions and collects the earliest buyers. Wallets that were early in *several* winners rank highest. You can add the top 100 to the watchlist in one click.
- **Live tracking:** polls each tracked wallet and decodes new swaps into BUY/SELL, with the token, SOL/USD size, market cap and liquidity. Each trade pops up with a sound and a desktop notification. It sends a 🔥 alert when several tracked whales buy the same token within a time window.
- A free private RPC (Helius/QuickNode) is recommended; the public RPC is heavily rate-limited.
