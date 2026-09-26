"""Command line entry point: python -m whalebot <command>."""

from __future__ import annotations

import argparse
import html
import logging
import re
import sys
import time

from .alerts import format_signal
from .bot import Bot, describe
from .commands import CommandListener
from .commands import top as top_signals
from .config import load_config
from .scoring import hard_filter


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="whalebot", description="DexScreener early-momentum + whale signal bot")
    ap.add_argument("-c", "--config", default="config.yaml", help="path to config.yaml")
    ap.add_argument("-v", "--verbose", action="store_true", help="debug logging (shows why tokens are skipped)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run", help="scan continuously, send alerts, and answer Telegram commands")
    top = sub.add_parser("top", help="print the best signals right now")
    top.add_argument("n", nargs="?", type=int, default=5)
    sub.add_parser("listen", help="only answer Telegram commands (no automatic alerts)")
    sub.add_parser("once", help="run a single scan cycle")
    chk = sub.add_parser("check", help="score one token right now")
    chk.add_argument("chain", help="solana, ethereum, base, bsc ...")
    chk.add_argument("address", help="token address")
    sub.add_parser("whales", help="poll tracked wallets once and print their recent trades")
    sub.add_parser("report", help="show how past signals actually performed")
    sub.add_parser("test-alert", help="send a test message to Telegram")
    args = ap.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    bot = Bot(load_config(args.config))

    if args.cmd == "run":
        if bot.alerter.telegram_enabled:
            CommandListener(bot).start_thread()
        try:
            bot.run_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    elif args.cmd == "listen":
        if not bot.alerter.telegram_enabled:
            print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
            return 1
        try:
            CommandListener(bot).run_forever()
        except KeyboardInterrupt:
            print("\nstopped")
    elif args.cmd == "top":
        result = top_signals(bot, max(1, args.n))
        for chunk in result if isinstance(result, list) else [result]:
            print(html.unescape(re.sub(r"<[^>]+>", "", chunk)) + "\n" + "-" * 60)
    elif args.cmd == "once":
        bot.scan()
        bot.track_outcomes()
    elif args.cmd == "check":
        pairs = bot.dex.pairs_for_tokens(args.chain, [args.address])
        pair = next(iter(pairs.values()), None)
        if pair is None:
            print("token not found on DexScreener")
            return 1
        since = int(time.time() - bot.cfg.whales.lookback_minutes * 60)
        sig, why = bot.evaluate(pair, bot.store.recent_whale_buys(args.chain, pair.token_address, since), force=True)
        print(describe(sig, why, pair))
        if sig is not None and why == "ok":
            reject = hard_filter(pair, bot.cfg.filters)
            if reject:
                print(f"\n(note: would be skipped by filters in live mode: {reject})")
            print("\n--- alert preview ---\n" + format_signal(sig))
    elif args.cmd == "whales":
        if not bot.cfg.whales.wallets:
            print("no wallets configured under `whales:` in config.yaml")
            return 1
        for t in bot.poll_whales():
            print(f"{t.wallet_label:>16} {t.side:4} {t.chain:8} {t.token} amount={t.amount:,.2f} "
                  f"spent={t.quote_amount:.3f} tx={t.tx[:16]}…")
    elif args.cmd == "report":
        perf = bot.store.performance()
        if not perf:
            print("no outcomes recorded yet — let the bot run for a while")
        else:
            print(f"{'after':>7} {'n':>5} {'avg x':>7} {'>=+20%':>7} {'>=2x':>6} {'<=-50%':>7} {'best':>7}")
            for r in perf:
                n = r["n"] or 1
                print(f"{r['minutes']:>6}m {r['n']:>5} {r['avg_mult']:>7.2f} {100 * r['up20'] / n:>6.0f}% "
                      f"{100 * r['x2'] / n:>5.0f}% {100 * r['down50'] / n:>6.0f}% {r['best']:>6.1f}x")
        print("\nrecent signals:")
        for s in bot.store.recent_signals():
            ts = time.strftime("%m-%d %H:%M", time.localtime(s["created_at"]))
            print(f"  {ts} {s['chain']:8} {s['symbol'] or '?':12} score {s['score']:>4.0f}  {s['results'] or ''}")
    elif args.cmd == "test-alert":
        if not bot.alerter.telegram_enabled:
            print("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")
            return 1
        bot.alerter.send("✅ <b>whalebot</b> is connected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
