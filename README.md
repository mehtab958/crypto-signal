# crypto-signal

A Grok-style crypto bot for Telegram. It's witty, blunt and has live market data. You chat
with it in DMs, or tag it in a group ("@SignalBot is this true?") and it fact-checks the
message you replied to. It runs on Claude.

## What it does

| Grok-style feature | How it works here |
| --- | --- |
| Personality with a **fun mode** | `/fun` (default) roasts bad takes and talks in crypto slang. `/regular` is direct and professional. |
| **Tag it anywhere** | In groups it only answers when @mentioned or when someone replies to it. In DMs it answers everything. |
| **"Is this true?"** | Reply to any message and tag the bot. It gets the original message plus its author and checks the claim with web search. |
| **Real-time knowledge** | Live web search for news, narratives and rumors, plus live price and market tools. |
| **Trading signals** | RSI, EMA 20/50/200, MACD, Bollinger bands, ATR, support/resistance, a scored verdict (STRONG BUY to STRONG SELL), and a stop-loss and take-profit. |
| Memory | Remembers the last `HISTORY_TURNS` exchanges per chat. `/reset` clears them. |

Commands: `/price BTC`, `/signal ETH 4h`, `/market`, `/fun`, `/regular`, `/reset`, `/help`.

`/price` answers straight from market data with no AI call, so it's fast and free. Everything
else goes through the AI, which picks which tools to call.

## Data sources (free, no keys needed)

- **CoinGecko**: prices, market cap, global stats, trending coins. A demo key via
  `COINGECKO_API_KEY` is optional and raises the rate limit.
- **Binance** candles for signals, falling back to **OKX** automatically. Binance blocks
  some regions, including the US.
- **Web search**: Claude's built-in web search tool.

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) and copy the token.
   To let it see mentions in groups, keep privacy mode on (the default). It will still get
   @mentions and replies to its own messages.
2. Get an Anthropic API key from https://platform.claude.com.
3. Install and configure:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then fill in ANTHROPIC_API_KEY and TELEGRAM_BOT_TOKEN
```

4. Run it:

```bash
python -m crypto_signal          # start the Telegram bot
python -m crypto_signal chat     # or chat in the terminal, no Telegram needed
```

## Configuration

See `.env.example`. The main options:

- `BOT_NAME`: the bot's name and persona name.
- `CLAUDE_MODEL`: defaults to `claude-opus-5`.
- `CLAUDE_EFFORT`: `low` / `medium` (default) / `high` / `xhigh` / `max`. Higher means
  deeper reasoning but slower and more expensive replies.
- `DEFAULT_MODE`: `fun` or `regular`.
- `ENABLE_WEB_SEARCH`: set to `false` to turn off web search.

If Claude declines a request, the API retries it on a recommended fallback model
(`fallbacks: "default"`).

## Project layout

```
crypto_signal/
  brain.py         persona, tools, Claude agent loop, per-chat memory
  telegram_bot.py  Telegram handlers (DMs, group mentions, reply-to context, commands)
  market.py        CoinGecko, Binance and OKX clients with caching
  signals.py       scores indicators into a verdict with levels
  indicators.py    RSI, EMA, SMA, MACD, Bollinger, ATR (pure functions)
  config.py        env / .env settings
tests/             offline tests (fake Claude client, fake market data)
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Disclaimer

Signals come from simple technical indicators. They are not financial advice. Do your own
research.
