# crypto-signal · whalebot

A DexScreener bot that looks for **newly launched tokens showing early momentum**, cross-checks them for
**rug/honeypot risk** and **social presence**, and boosts the score when **whale / smart-money wallets you
track buy in**. Alerts go to Telegram (and the console). It also records how every signal actually
performed, so you can judge the bot on results instead of hope.

> ⚠️ **Read this first.** No bot can reliably tell you which coin will pump *before* it pumps. Most new
> tokens go to zero, many are built to rug the people who buy them, and "whale" wallets can themselves be
> insiders who dump on followers. Use this as a **filter that shortlists candidates for you to research
> faster**, not as an autopilot. Trade small amounts you can afford to lose, and run `report` for
> a few days before you trust any threshold.

## How it works

```
 tracked whale wallets ──► new buys ─────────────┐
 (Solana RPC / Etherscan V2)                     │
                                                 ▼
 DexScreener feeds ─► candidate tokens ─► hard filters ─► safety check ─► social check ─► score 0-100 ─► alert
 (new profiles, boosts)                  (age, liq, mcap,  (RugCheck /      (X, TG members,              (Telegram)
                                          txns, not late)   GoPlus)          website, boosts)
                                                                                                   │
                                                      outcome tracker: price at +15m / 1h / 4h / 24h ◄┘
```

| Component | Max pts | What it measures |
|---|---|---|
| Momentum | 35 | 5m & 1h buy/sell ratio, 5m volume acceleration vs 1h, volume/liquidity turnover, healthy (not parabolic) price action |
| Whales | 30 | Tracked wallets buying in the last `lookback_minutes`; several different whales in the same token scores highest |
| Safety | 20 | Solana: RugCheck risk score, dangerous risks (mint/freeze authority...), LP lock. EVM: GoPlus honeypot, tax, blacklist, hidden owner, top-10 holder concentration, LP lock |
| Social | 10 | X/Telegram/website present, website up, Telegram member count, paid DexScreener boosts |
| Early | 5 | Bonus for pairs under 1h / 3h / 8h old |

Tokens that fail a hard filter (for example too old, too little liquidity, already up 400% in 1h, a honeypot,
or a dangerous RugCheck result) never alert. Whale buys also relax the age filter, and with
`whale_alert_always: true` they alert even below the threshold, but only if they pass safety.

When a tracked whale **sells** a token the bot already signalled, you get a **🚪 WHALE EXIT** alert.

## Setup

```bash
git clone https://github.com/mehtab958/crypto-signal && cd crypto-signal
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp config.example.yaml config.yaml   # tune filters, chains, add whale wallets
cp .env.example .env                 # add your secrets
```

### Telegram alerts
1. Message [@BotFather](https://t.me/BotFather), run `/newbot`, and copy the token into `TELEGRAM_BOT_TOKEN`.
2. Send your new bot any message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy
   `chat.id` into `TELEGRAM_CHAT_ID`. For a group, add the bot to the group and use the group's (negative) id.
3. Run `python -m whalebot test-alert`.

The same bot token is used to read member counts of projects' public Telegram groups.

### Whale wallets
Add wallets under `whales:` in `config.yaml`:

```yaml
whales:
  lookback_minutes: 30
  solana:
    - address: "7xKX...yourWallet"
      label: "early-sniper-1"
      weight: 1.5        # trust this wallet more
  evm:
    - address: "0xabc..."
      chain: base
      label: "base-degen"
```

**Finding good wallets matters more than anything else here.** Take tokens that already did 10x or more, look at
their early buyers or "top traders" on GMGN, Birdeye, Cielo, Arkham or DexScreener's top traders tab, and keep
wallets that are **profitable across many different tokens** over weeks, not wallets with one lucky hit. Leave
out obvious dev/insider wallets and bots that buy everything.

- **Solana** needs an RPC. The public `api.mainnet-beta.solana.com` works for a couple of wallets but is
  heavily rate-limited, so for more wallets use a free Helius/QuickNode/Triton RPC URL in `SOLANA_RPC_URL`.
- **EVM** needs a free [Etherscan V2](https://etherscan.io/apis) API key in `ETHERSCAN_API_KEY`.
  One key covers Ethereum, BSC, Base, Arbitrum, Polygon and more.

Only transactions the wallet itself sent count as buys, so spam tokens airdropped to whale wallets are ignored.

## Quick start: get signals with commands

The default settings work without any whale wallets, so you only need a Telegram bot to start:

```bash
pip install -r requirements.txt
cp .env.example .env          # put TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in it (see Telegram alerts above)
python -m whalebot run        # automatic alerts + answers your commands in Telegram
```

Then send these to your bot in Telegram:

| Command | What you get |
|---|---|
| `/top` or `/top 5` | The best-scoring new tokens right now, even if none crossed the alert threshold |
| `/check <address>` | Full score + safety check for any token (chain auto-detected). You can also just paste an address |
| `/check base 0x…` | Same thing with the chain given explicitly |
| `/whales` | Latest buys/sells of your tracked wallets |
| `/report` | Win rate of past signals at +15m / 1h / 4h / 24h |
| `/status` | Chains, filters, threshold, alerts on or off |
| `/threshold 70` | Change the alert threshold without restarting |
| `/pause` · `/resume` | Stop or restart automatic alerts; commands keep working |

The bot only answers the chat in `TELEGRAM_CHAT_ID` and ignores everyone else.
No Telegram? `python -m whalebot top` prints the same `/top` signals in your terminal.

## Usage

```bash
python -m whalebot run                         # scan every scan_interval_seconds, alert, answer Telegram commands
python -m whalebot listen                      # answer Telegram commands only, no automatic alerts
python -m whalebot top 5                       # best 5 signals right now, printed in the terminal
python -m whalebot -v once                     # one cycle; -v shows why each token was skipped
python -m whalebot check solana <mint>         # score any token right now and preview the alert
python -m whalebot check base 0x...            #   (works for EVM chains too)
python -m whalebot whales                      # poll your wallets once and print their trades
python -m whalebot report                      # how past signals performed (+15m / 1h / 4h / 24h)
python -m whalebot test-alert                  # check Telegram is wired up
```

Example alert:

```
🔥 STRONG 77/100 — $BOOM (Vine BOOM)
solana · pumpswap · age 11m
MC $61.8K · Liq $21.1K · Vol1h $123.8K
Δ 5m +54.5% · 1h +19.6% · Buys/Sells 5m 296/124

✅ 🐋 1 whale(s) bought: early-sniper-1
✅ buy pressure 5m 296/124
✅ volume accelerating 4.8x
✅ 1h vol 6.6x liquidity
✅ socials: X TG Web
```

### Keeping it running 24/7
Run it on a small VPS inside `tmux`/`screen`, or as a systemd service:

```ini
# /etc/systemd/system/whalebot.service
[Service]
WorkingDirectory=/opt/crypto-signal
ExecStart=/opt/crypto-signal/.venv/bin/python -m whalebot run
Restart=always
[Install]
WantedBy=multi-user.target
```

## Tuning

- **Too many alerts?** Raise `scoring.alert_threshold` (70+), raise `filters.min_liquidity_usd`, and lower
  `filters.max_age_hours`.
- **Too few?** Lower the threshold, or add more (good) whale wallets. Whale buys are the strongest signal.
- Check `python -m whalebot report` after a few days. If `avg x` at 1h is below 1 and `<=-50%` is high,
  your settings are catching tops or rugs, so tighten them.

## Limitations (honest list)

- DexScreener's free API has no trade-by-trade data, so "whale buys" come only from wallets **you** list.
  The bot doesn't discover unknown whales automatically.
- X/Twitter follower counts and mention velocity need paid APIs, so the social score only covers presence,
  website liveness and Telegram size.
- Safety APIs catch common scams (honeypots, taxes, mint/freeze authority, concentrated holders) but not
  everything. A "safe" score doesn't mean the team won't dump.
- Signals are delayed by `scan_interval_seconds` plus API latency. Sniper bots working at the block level
  will always be faster at launch, so this bot's edge is confluence (momentum + safety + whales), not speed.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Not financial advice.
