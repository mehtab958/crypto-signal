"""DexScreener pump scanner for iPhone.   Run:  streamlit run dexscan/app.py"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))
from dexscan.scanner import SOURCES, scan  # noqa: E402

st.set_page_config(page_title="Pump Scanner", page_icon="🚀")
st.title("🚀 DexScreener Pump Scanner")
st.caption("Finds tokens pumping right now and flags rug-pull risk. It shows momentum that already happened. "
           "It cannot predict what pumps next, and most small tokens that pump later dump.")

with st.sidebar:
    sources = st.multiselect("Where to look", list(SOURCES), default=list(SOURCES))
    chains = st.multiselect("Chains (empty = all)", ["solana", "ethereum", "base", "bsc", "arbitrum", "robinhood"])
    min_liq = st.number_input("Min liquidity ($)", 0, 10_000_000, 20_000, step=5_000)
    min_vol = st.number_input("Min 1h volume ($)", 0, 10_000_000, 5_000, step=1_000)
    hide_avoid = st.checkbox("Hide AVOID", value=True)
query = st.text_input("Or search a token / pair (optional)", placeholder="e.g. BONK or a contract address")

if st.button("Scan now", type="primary"):
    with st.spinner("Scanning DexScreener..."):
        st.session_state.results = scan(tuple(sources), query.strip(), chains, min_liq, min_vol)

results = st.session_state.get("results")
if results is not None:
    shown = [r for r in results if not (hide_avoid and r.verdict == "AVOID")]
    st.write(f"{len(shown)} tokens shown of {len(results)} scanned. Tap a row's links to check it.")
    for r in shown:
        icon = {"MOMENTUM": "🟢", "WATCH": "🟡", "WEAK": "⚪", "AVOID": "🔴"}[r.verdict]
        with st.expander(f"{icon} {r.verdict} · {r.symbol} ({r.chain}) · score {r.score:.0f} · 1h {r.change_h1:+.1f}%"):
            c1, c2, c3 = st.columns(3)
            c1.metric("5m / 1h", f"{r.change_m5:+.1f}%", f"{r.change_h1:+.1f}% 1h")
            c2.metric("Liquidity", f"${r.liquidity:,.0f}")
            c3.metric("1h volume", f"${r.volume_h1:,.0f}")
            st.write(f"**6h** {r.change_h6:+.1f}% · **24h** {r.change_h24:+.1f}% · **Buys/sells 1h** {r.buy_sell_h1} · "
                     f"**Age** {r.age_hours:.1f} h · **FDV** ${r.fdv:,.0f} · **Price** ${r.price:.10g}")
            if r.flags:
                st.warning("Risk flags: " + "; ".join(r.flags))
            st.markdown(f"[Open on DexScreener]({r.dexscreener}) · [Safety check (honeypot / rug)]({r.safety_check})")
    if shown:
        st.download_button("Download table (CSV)", pd.DataFrame([vars(r) for r in shown]).to_csv(index=False),
                           "pump_scan.csv", "text/csv")

st.info("Before buying anything: run the safety check link, confirm liquidity is locked, never buy tokens you cannot "
        "sell (honeypots), and only use money you can lose completely. Boosted = someone paid for the listing.")
