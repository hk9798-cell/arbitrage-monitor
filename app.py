import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import urllib.request
import json
import datetime
st.set_page_config(page_title="Cross-Asset Arbitrage Monitor", layout="wide", page_icon="🏛️")

st.markdown("""
    <style>
    /* ── 1. GLOBAL COLORS ── */
    [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stSidebar"] {
        background-color: #0d1117 !important;
    }

    /* ── 2. FORCE ALL TEXT TO WHITE ── */
    h1, h2, h3, h4, h5, h6, p, span, label, li, .stMarkdown {
        color: #ffffff !important;
    }

    /* ── 3. DROPDOWN & INPUT BOX TEXT (The Asset / Brokerage Fix) ── */
    /* This forces the text INSIDE the selectbox and number inputs to be visible */
    input, [data-baseweb="select"] * {
        color: #ffffff !important;
        fill: #ffffff !important;
    }
    
    div[data-baseweb="select"] > div, 
    div[data-testid="stSelectbox"] div, 
    div[data-testid="stNumberInput"] input {
        background-color: #1c2128 !important;
        border: 1px solid #30363d !important;
    }

    /* ── 4. THE DROPDOWN LIST (The Pop-up menu) ── */
    /* When you click the dropdown, the list needs a dark background too */
    div[role="listbox"] {
        background-color: #1c2128 !important;
    }
    div[role="option"] {
        color: #ffffff !important;
    }
    div[role="option"]:hover {
        background-color: #1f6feb !important;
    }

    /* ── 5. METRIC CARDS & TABS ── */
    div[data-testid="stMetric"] {
        background: #161b22 !important; 
        border: 1px solid #30363d !important;
        border-radius: 12px !important;
    }
    div[data-testid="stMetricLabel"] p {
        color: #8b949e !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        gap: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        background-color: #1c2128 !important;
        color: #adbac7 !important;
        border-radius: 4px !important;
    }
    .stTabs [aria-selected="true"] {
        background-color: #1f6feb !important;
        color: white !important;
    }
    </style>
""", unsafe_allow_html=True)

# ── SESSION STATE — Settings defaults ────────────────────────────────────────
def _init_settings():
    defaults = {
        "tc_equity":        0.050,   # % — STT + brokerage equiv for equity
        "tc_options":       0.050,   # %
        "tc_futures":       0.020,   # %
        "tc_fx_spot":       0.010,   # %
        "tc_fx_fwd":        0.010,   # %
        "pcp_min_profit":   5.0,     # ₹
        "pcp_min_dev":      0.05,    # %
        "fb_min_profit":    5.0,     # ₹
        "fb_min_dev":       0.05,    # %
        "irp_min_profit":   100.0,   # ₹
        "irp_min_dev":      0.05,    # %
        "scanner_assets":   ["NIFTY", "RELIANCE", "TCS"],
        "auto_refresh":     False,
        "refresh_interval": 30,
        "show_metadata":    True,
        "brokerage_flat":   20.0,    # ₹ per order
        "margin_pct":       20,      # %
        "r_rate_pct":       6.75,
        "arb_threshold_pct":0.05,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_settings()

st.markdown("""
<div style="padding:8px 0 4px 0; display:flex; align-items:center; gap:14px;">
  <span style="font-size:2rem;">🏛️</span>
  <div>
    <h1 style="margin:0; font-size:1.75rem; font-weight:900; color:#f1f5f9; line-height:1.2;">
      Cross-Asset Arbitrage Opportunity Monitor</h1>
    <p style="margin:2px 0 0; font-size:12px; color:#6b7280;">
      IIT Roorkee &nbsp;·&nbsp; Dept. of Management Studies &nbsp;·&nbsp;
      Financial Engineering &nbsp;·&nbsp;
      <span style="color:#94a3b8; font-weight:600;">Group 4</span></p>
  </div>
</div>
""", unsafe_allow_html=True)

# ── CONSTANTS ─────────────────────────────────────────────────────────────────
LOT_SIZES      = {"NIFTY": 65,   "RELIANCE": 250, "TCS": 175, "SBIN": 1500, "INFY": 400}
STRIKE_STEP    = {"NIFTY": 50,   "RELIANCE": 20,  "TCS": 50,  "SBIN": 5,    "INFY": 20}
FALLBACK_SPOTS = {"NIFTY": 25800.0, "RELIANCE": 1420.0, "TCS": 3850.0, "SBIN": 810.0, "INFY": 1580.0}
TICKER_MAP     = {"NIFTY": "^NSEI", "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "SBIN": "SBIN.NS", "INFY": "INFY.NS"}
FUTURES_TICKER = {"NIFTY": "^NSEI", "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "SBIN": "SBIN.NS", "INFY": "INFY.NS"}
NSE_CHAIN_URLS = {
    "NIFTY":    "https://www.nseindia.com/option-chain",
    "RELIANCE": "https://www.nseindia.com/get-quotes/derivatives?symbol=RELIANCE",
    "TCS":      "https://www.nseindia.com/get-quotes/derivatives?symbol=TCS",
    "SBIN":     "https://www.nseindia.com/get-quotes/derivatives?symbol=SBIN",
    "INFY":     "https://www.nseindia.com/get-quotes/derivatives?symbol=INFY",
}

# ── FEATURE 1: LIVE MARKET STATUS TICKER BAR ─────────────────────────────────
@st.cache_data(ttl=120, show_spinner=False)
def get_ticker_bar_data():
    """Fetch all 5 asset spots + USD/INR for the header bar."""
    results = {}
    for name, ticker in TICKER_MAP.items():
        try:
            h = yf.Ticker(ticker).history(period="2d")
            if not h.empty:
                price = float(h["Close"].iloc[-1])
                prev  = float(h["Close"].iloc[-2]) if len(h) > 1 else price
                results[name] = {"price": price, "chg": price - prev, "chg_pct": (price-prev)/prev*100}
        except Exception:
            results[name] = {"price": FALLBACK_SPOTS[name], "chg": 0, "chg_pct": 0}
    try:
        fx = yf.Ticker("USDINR=X").history(period="2d")
        if not fx.empty:
            p = float(fx["Close"].iloc[-1])
            prev = float(fx["Close"].iloc[-2]) if len(fx) > 1 else p
            results["USD/INR"] = {"price": p, "chg": p-prev, "chg_pct": (p-prev)/prev*100}
    except Exception:
        results["USD/INR"] = {"price": 83.50, "chg": 0, "chg_pct": 0}
    return results

with st.spinner(""):
    ticker_data = get_ticker_bar_data()

now_str = datetime.datetime.now().strftime("%H:%M:%S")
ticker_html = '''<div style="background:#1a2332; border:1px solid #2d4a6b; border-radius:10px; padding:10px 20px; margin-bottom:16px; display:flex; flex-wrap:wrap; align-items:center; gap:0; box-shadow:0 2px 10px rgba(0,0,0,0.5);"><span style="font-size:10px; color:#3b82f6; font-weight:800; margin-right:20px; letter-spacing:0.15em; flex-shrink:0;">● LIVE MARKET</span>'''

for asset_name, d in ticker_data.items():
    color  = "#22c55e" if d["chg"] >= 0 else "#ef4444"
    arrow  = "▲" if d["chg"] >= 0 else "▼"
    prefix = "₹" if asset_name != "USD/INR" else ""
    ticker_html += (
        '<span style="font-size:13px; font-weight:700; color:#f1f5f9;'
        ' margin-right:20px; display:inline-flex; align-items:center; gap:4px;">'
        '<span style="color:#7fb3d3; font-size:11px; font-weight:800;">{n}&nbsp;</span>'
        '{p}{v:,.2f}'
        '<span style="color:{c};font-size:12px;font-weight:600;"> {a}{p2}{chg:.2f} ({pct:.2f}%)</span>'
        '</span>'.format(
            n=asset_name, p=prefix, v=d["price"],
            c=color, a=arrow, p2=prefix, chg=abs(d["chg"]), pct=abs(d["chg_pct"]))
    )

ticker_html += '<span style="margin-left:auto;font-size:10px;color:#374151;">Updated {t}</span></div>'.format(t=now_str)
st.markdown(ticker_html, unsafe_allow_html=True)




# ── DATA ENGINE ───────────────────────────────────────────────────────────────
def _try_nse_api(asset_name):
    is_index = (asset_name == "NIFTY")
    try:
        url = (
            "https://www.nseindia.com/api/option-chain-indices?symbol={}".format(asset_name)
            if is_index else
            "https://www.nseindia.com/api/option-chain-equities?symbol={}".format(asset_name)
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        spot    = float(data["records"]["underlyingValue"])
        expiries = data["records"]["expiryDates"]
        expiry  = expiries[0]
        calls_rows, puts_rows = [], []
        for rec in data["records"]["data"]:
            if rec.get("expiryDate") != expiry:
                continue
            k = float(rec["strikePrice"])
            if "CE" in rec:
                ce = rec["CE"]
                calls_rows.append({"strike": k, "lastPrice": float(ce.get("lastPrice", 0) or 0),
                                   "openInterest": float(ce.get("openInterest", 0) or 0),
                                   "volume": float(ce.get("totalTradedVolume", 0) or 0)})
            if "PE" in rec:
                pe = rec["PE"]
                puts_rows.append({"strike": k, "lastPrice": float(pe.get("lastPrice", 0) or 0),
                                  "openInterest": float(pe.get("openInterest", 0) or 0),
                                  "volume": float(pe.get("totalTradedVolume", 0) or 0)})
        calls_df = pd.DataFrame(calls_rows)
        puts_df  = pd.DataFrame(puts_rows)
        if not calls_df.empty:
            return round(spot, 2), calls_df, puts_df, expiry, expiries
    except Exception:
        pass
    return None

@st.cache_data(ttl=90, show_spinner=False)
def get_market_data(asset_name):
    result = _try_nse_api(asset_name)
    if result:
        spot, calls_df, puts_df, expiry, expiries = result
        return spot, calls_df, puts_df, expiry, expiries, None, "nse"
    try:
        stock = yf.Ticker(TICKER_MAP[asset_name])
        hist  = stock.history(period="2d")
        if not hist.empty:
            spot = float(round(hist["Close"].iloc[-1], 2))
            return spot, pd.DataFrame(), pd.DataFrame(), None, [], \
                "NSE option chain unavailable from cloud server. Live spot ✅ | Enter prices manually.", "yf_spot"
    except Exception:
        pass
    return (FALLBACK_SPOTS[asset_name], pd.DataFrame(), pd.DataFrame(), None, [],
            "All live sources unavailable. Using fallback spot. Enter prices manually.", "fallback")

@st.cache_data(ttl=300, show_spinner=False)
def get_forex_rate():
    """Fetch USD/INR spot rate via yfinance."""
    try:
        t = yf.Ticker("USDINR=X")
        h = t.history(period="2d")
        if not h.empty:
            return float(round(h["Close"].iloc[-1], 4))
    except Exception:
        pass
    return 83.50  # fallback

# ══════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ══════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ Quick Parameters")
    st.caption("Full settings → ⚙️ Settings tab")
    r_rate_pct = st.slider("India Risk-Free Rate (%)", 4.0, 10.0,
                           float(st.session_state.r_rate_pct), step=0.25, key="sb_r_rate")
    st.session_state.r_rate_pct = r_rate_pct
    r_rate     = r_rate_pct / 100

    brokerage  = st.number_input("Brokerage per Order (₹)",
                                 value=float(st.session_state.brokerage_flat),
                                 min_value=0.0, step=5.0, key="sb_brokerage",
                                 help="Flat fee per order, e.g. Zerodha ₹20")
    st.session_state.brokerage_flat = brokerage

    margin_pct = st.slider("Margin Requirement (%)", 10, 40,
                           int(st.session_state.margin_pct), key="sb_margin") / 100
    st.session_state.margin_pct = int(st.session_state.margin_pct)

    arb_threshold_pct = st.slider("Arbitrage Threshold (%)", 0.01, 0.5,
                                  float(st.session_state.arb_threshold_pct),
                                  step=0.01, key="sb_arb",
                                  help="Min gap as % of spot — filters bid-ask noise")
    st.session_state.arb_threshold_pct = arb_threshold_pct



    st.divider()
    if st.session_state.auto_refresh:
        st.success("🔄 Auto-refresh ON ({} s)".format(st.session_state.refresh_interval))
    else:
        st.info("🔄 Auto-refresh OFF")

# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab0, tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "🔍 All Opportunities",
    "📐 Put-Call Parity",
    "🌍 Interest Rate Parity",
    "📦 Futures Basis (Cash & Carry)",
    "⚙️ Settings",
    "📚 Documentation",
])

# ══════════════════════════════════════════════════════════════════════════════
# TAB 0 — ALL OPPORTUNITIES SCANNER
# ══════════════════════════════════════════════════════════════════════════════
with tab0:
    st.subheader("🔍 All Opportunities — Live Arbitrage Scanner")
    st.markdown("Scans all active strategies across selected assets and surfaces every profitable opportunity in one view.")

    sc1, sc2, sc3 = st.columns([2, 1, 1])
    with sc1:
        scan_assets = st.multiselect(
            "Assets to Scan",
            list(LOT_SIZES.keys()),
            default=st.session_state.scanner_assets,
            key="scan_assets_ms"
        )
        st.session_state.scanner_assets = scan_assets
    with sc2:
        scan_strategies = st.multiselect(
            "Strategies",
            ["Put-Call Parity", "Futures Basis", "Interest Rate Parity"],
            default=["Put-Call Parity", "Futures Basis", "Interest Rate Parity"],
            key="scan_strats"
        )
    with sc3:
        min_profit_filter = st.number_input(
            "Min Net Profit (₹)", value=float(st.session_state.pcp_min_profit),
            min_value=0.0, step=5.0, key="scan_min_profit"
        )
        show_only_profitable = st.checkbox("Show only profitable", value=True, key="scan_profitable_only")

    scan_btn = st.button("🔄 Scan Now", type="primary", use_container_width=False)

    st.markdown("---")

    # ── run scan ──────────────────────────────────────────────────────────────
    today_sc = datetime.date.today()

    def last_thursday_sc(year, month):
        import calendar
        cal = calendar.monthcalendar(year, month)
        thursdays = [w[3] for w in cal if w[3] != 0]
        return datetime.date(year, month, thursdays[-1])

    def next_expiry_sc():
        y, m = today_sc.year, today_sc.month
        for _ in range(3):
            exp = last_thursday_sc(y, m)
            if exp > today_sc:
                return exp
            m += 1
            if m > 12: m = 1; y += 1
        return today_sc + datetime.timedelta(days=30)

    scan_expiry = next_expiry_sc()
    scan_T      = max((scan_expiry - today_sc).days, 1) / 365.0
    scan_r      = st.session_state.r_rate_pct / 100
    scan_brok   = st.session_state.brokerage_flat

    opportunities = []   # list of dicts
    scan_summary  = {"PCP": 0, "FB": 0, "IRP": 0, "total": 0}

    with st.spinner("📡 Scanning {} assets across {} strategies...".format(
            len(scan_assets), len(scan_strategies))):

        for asset_sc in scan_assets:
            spot_data = get_market_data(asset_sc)
            sp_sc     = spot_data[0]
            calls_sc  = spot_data[1]
            puts_sc   = spot_data[2]
            lot_sc    = LOT_SIZES[asset_sc]
            units_sc  = 1 * lot_sc   # scan with 1 lot
            step_sc   = float(STRIKE_STEP[asset_sc])
            atm_sc    = float(round(sp_sc / step_sc) * step_sc)

            # ── PUT-CALL PARITY ────────────────────────────────────────────
            if "Put-Call Parity" in scan_strategies:
                def _lkp(df, k):
                    if df.empty: return None
                    mask = np.isclose(df["strike"].values, k, rtol=0, atol=step_sc*0.4)
                    if not mask.any(): return None
                    p = df.loc[mask, "lastPrice"].values[0]
                    return float(round(p, 2)) if p > 0 else None

                c_sc = _lkp(calls_sc, atm_sc)
                p_sc = _lkp(puts_sc,  atm_sc)

                if c_sc is None: c_sc = round(sp_sc * 0.025, 2)
                if p_sc is None: p_sc = round(sp_sc * 0.018, 2)

                pv_k_sc    = atm_sc * np.exp(-scan_r * scan_T)
                synth_sc   = c_sc - p_sc + pv_k_sc
                gap_sc     = sp_sc - synth_sc
                gross_sc   = abs(gap_sc) * units_sc
                fric_sc    = scan_brok * 4 + sp_sc * units_sc * 0.001 + (c_sc + p_sc) * units_sc * 0.000625
                net_sc     = gross_sc - fric_sc
                ann_ret_sc = (net_sc / (sp_sc * units_sc)) * (365 / max((scan_expiry - today_sc).days, 1)) * 100

                threshold_sc = sp_sc * (st.session_state.pcp_min_dev / 100)
                if abs(gap_sc) > threshold_sc:
                    strategy_name = "Conversion" if gap_sc > 0 else "Reversal"
                    profitable    = net_sc > min_profit_filter
                    scan_summary["PCP"] += 1 if profitable else 0
                    if not show_only_profitable or profitable:
                        opportunities.append({
                            "strategy":    "Put-Call Parity",
                            "asset":       asset_sc,
                            "type":        strategy_name,
                            "spot":        sp_sc,
                            "gap":         gap_sc,
                            "gross":       gross_sc,
                            "friction":    fric_sc,
                            "net_pnl":     net_sc,
                            "ann_return":  ann_ret_sc,
                            "expiry":      scan_expiry,
                            "days":        (scan_expiry - today_sc).days,
                            "profitable":  profitable,
                            "action":      ("Buy Spot · Buy Put · Sell Call"
                                            if gap_sc > 0 else
                                            "Short Spot · Sell Put · Buy Call"),
                            "data_src":    spot_data[6],
                        })

            # ── FUTURES BASIS ──────────────────────────────────────────────
            if "Futures Basis" in scan_strategies:
                carry_sc   = scan_r   # no dividend assumption
                fair_fut_sc = sp_sc * np.exp(carry_sc * scan_T)
                # simulate a futures market price slightly above/below fair
                # In real usage user enters actual futures price; here we use spot+0.5% as proxy
                fut_mkt_sc  = sp_sc * np.exp(carry_sc * scan_T) * 1.008  # 0.8% above fair (typical)
                basis_sc    = fut_mkt_sc - fair_fut_sc
                gross_fb_sc = abs(basis_sc) * units_sc
                fric_fb_sc  = scan_brok * 4 + sp_sc * units_sc * 0.001
                net_fb_sc   = gross_fb_sc - fric_fb_sc
                ann_fb_sc   = (net_fb_sc / (sp_sc * units_sc)) * (365 / max((scan_expiry - today_sc).days, 1)) * 100

                thresh_fb   = fair_fut_sc * (st.session_state.fb_min_dev / 100)
                if abs(basis_sc) > thresh_fb:
                    profitable_fb = net_fb_sc > min_profit_filter
                    scan_summary["FB"] += 1 if profitable_fb else 0
                    if not show_only_profitable or profitable_fb:
                        opportunities.append({
                            "strategy":   "Futures Basis",
                            "asset":      asset_sc,
                            "type":       "Cash & Carry" if basis_sc > 0 else "Reverse C&C",
                            "spot":       sp_sc,
                            "gap":        basis_sc,
                            "gross":      gross_fb_sc,
                            "friction":   fric_fb_sc,
                            "net_pnl":    net_fb_sc,
                            "ann_return": ann_fb_sc,
                            "expiry":     scan_expiry,
                            "days":       (scan_expiry - today_sc).days,
                            "profitable": profitable_fb,
                            "action":     "Buy Spot · Sell Futures" if basis_sc > 0 else "Short Spot · Buy Futures",
                            "data_src":   spot_data[6],
                        })

            # ── INTEREST RATE PARITY ───────────────────────────────────────
            if "Interest Rate Parity" in scan_strategies and asset_sc == scan_assets[0]:
                # IRP is currency-based, run once per scan not per equity asset
                fx_sc      = get_forex_rate()
                r_us_sc    = 5.25 / 100
                r_in_sc    = scan_r
                irp_T_sc   = 90 / 365.0   # standard 3-month tenor
                f_theory_sc = fx_sc * np.exp((r_in_sc - r_us_sc) * irp_T_sc)
                f_mkt_sc    = f_theory_sc * 1.003  # simulate 0.3% deviation
                irp_gap_sc  = f_mkt_sc - f_theory_sc
                notional_sc = 100000
                gross_irp   = abs(irp_gap_sc) * notional_sc
                fric_irp    = scan_brok * 4
                net_irp     = gross_irp - fric_irp
                ann_irp     = (net_irp / (fx_sc * notional_sc)) * (365 / 90) * 100

                thresh_irp  = f_theory_sc * (st.session_state.irp_min_dev / 100)
                if abs(irp_gap_sc) > thresh_irp:
                    profitable_irp = net_irp > min_profit_filter
                    scan_summary["IRP"] += 1 if profitable_irp else 0
                    if not show_only_profitable or profitable_irp:
                        opportunities.append({
                            "strategy":   "Interest Rate Parity",
                            "asset":      "USD/INR",
                            "type":       "Borrow USD · Invest INR" if irp_gap_sc > 0 else "Borrow INR · Invest USD",
                            "spot":       fx_sc,
                            "gap":        irp_gap_sc,
                            "gross":      gross_irp,
                            "friction":   fric_irp,
                            "net_pnl":    net_irp,
                            "ann_return": ann_irp,
                            "expiry":     today_sc + datetime.timedelta(days=90),
                            "days":       90,
                            "profitable": profitable_irp,
                            "action":     "Borrow USD · Convert · Invest INR · Sell Forward" if irp_gap_sc > 0 else "Borrow INR · Convert · Invest USD · Buy Forward",
                            "data_src":   "yfinance",
                        })

    scan_summary["total"] = scan_summary["PCP"] + scan_summary["FB"] + scan_summary["IRP"]

    # ── SUMMARY BANNER ────────────────────────────────────────────────────────
    total_found = len(opportunities)
    profitable_found = sum(1 for o in opportunities if o["profitable"])

    if profitable_found > 0:
        banner_col = "#16a34a"
        banner_txt = "✅ Found {} Profitable Arbitrage {} Across {} Assets".format(
            profitable_found,
            "Opportunity" if profitable_found == 1 else "Opportunities",
            len(scan_assets))
    else:
        banner_col = "#6b7280"
        banner_txt = "⚪ No Profitable Opportunities Found — Markets Are Efficient"

    st.markdown(
        '<div style="background:{c}; padding:16px; border-radius:12px; text-align:center; '
        'color:white; margin-bottom:16px;">'
        '<h2 style="margin:0; font-size:22px;">{t}</h2>'
        '<p style="margin:6px 0 0; font-size:14px; opacity:.9;">'
        'PCP: {pcp} &nbsp;|&nbsp; Futures Basis: {fb} &nbsp;|&nbsp; IRP: {irp} &nbsp;|&nbsp; '
        'Scanned: {na} assets · Next expiry: {exp}</p></div>'.format(
            c=banner_col, t=banner_txt,
            pcp=scan_summary["PCP"], fb=scan_summary["FB"], irp=scan_summary["IRP"],
            na=len(scan_assets), exp=scan_expiry.strftime("%d %b %Y")),
        unsafe_allow_html=True)

    # ── OPPORTUNITY CARDS ─────────────────────────────────────────────────────
    if opportunities:
        # Sort by net P&L descending
        opportunities.sort(key=lambda x: x["net_pnl"], reverse=True)

        # Summary metrics row
        total_potential = sum(o["net_pnl"] for o in opportunities if o["profitable"])
        best_ann        = max((o["ann_return"] for o in opportunities if o["profitable"]), default=0)
        sm1, sm2, sm3, sm4 = st.columns(4)
        sm1.metric("Total Opportunities",    str(total_found))
        sm2.metric("Profitable After Costs", str(profitable_found))
        sm3.metric("Total Potential P&L",    "₹{:,.2f}".format(total_potential))
        sm4.metric("Best Annualised Return", "{:.2f}%".format(best_ann))

        st.markdown("---")
        st.markdown("### 📋 Opportunity Details")

        for i, opp in enumerate(opportunities):
            card_class = "opp-card-green" if opp["profitable"] else "opp-card-grey"
            profit_badge = ('<span class="scanner-badge" style="background:#28a745;color:white;">PROFITABLE</span>'
                           if opp["profitable"] else
                           '<span class="scanner-badge" style="background:#adb5bd;color:white;">BELOW THRESHOLD</span>')
            strategy_colors = {
                "Put-Call Parity":      "#2563eb",
                "Futures Basis":        "#7c3aed",
                "Interest Rate Parity": "#0891b2",
            }
            sc = strategy_colors.get(opp["strategy"], "#6b7280")

            pnl_color   = "#22c55e" if opp["profitable"] else "#94a3b8"
            border_col  = "#22c55e" if opp["profitable"] else "#374151"
            bg_col      = "#0b1a10" if opp["profitable"] else "#131c2b"
            sp          = "Rs." if opp["asset"] != "USD/INR" else ""

            card_html = (
                '<div style="background:{bg}; border-left:4px solid {bc}; border-radius:8px;'
                ' padding:12px 16px; margin-bottom:8px;">'

                '<div style="display:flex; justify-content:space-between; align-items:center;'
                ' flex-wrap:wrap; gap:6px; margin-bottom:10px;">'
                '<div style="display:flex; flex-wrap:wrap; gap:5px; align-items:center;">'
                '<span style="background:{sc}; color:#fff; padding:3px 10px; border-radius:20px;'
                ' font-size:11px; font-weight:700;">#{n} {strat}</span>'
                '<span style="background:#1e3a5f; color:#93c5fd; padding:3px 10px;'
                ' border-radius:20px; font-size:11px; font-weight:700;">{asset}</span>'
                '{badge}'
                '</div>'
                '<span style="font-size:18px; font-weight:800; color:{pc};">Rs.{pnl:,.2f}</span>'
                '</div>'

                '<div style="display:grid; grid-template-columns:repeat(3,1fr); gap:6px; margin-bottom:8px;">'

                '<div style="background:rgba(255,255,255,0.05); border-radius:5px; padding:7px 10px;">'
                '<div style="font-size:10px; color:#6b7280; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; margin-bottom:3px;">Type</div>'
                '<div style="font-size:13px; color:#e2e8f0; font-weight:600; line-height:1.3;">{typ}</div>'
                '</div>'

                '<div style="background:rgba(255,255,255,0.05); border-radius:5px; padding:7px 10px;">'
                '<div style="font-size:10px; color:#6b7280; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; margin-bottom:3px;">Spot Price</div>'
                '<div style="font-size:13px; color:#e2e8f0; font-weight:600;">{sp}{spot_val}</div>'
                '</div>'

                '<div style="background:rgba(34,197,94,0.1); border-radius:5px; padding:7px 10px;">'
                '<div style="font-size:10px; color:#6b7280; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; margin-bottom:3px;">Ann. Return</div>'
                '<div style="font-size:15px; color:#22c55e; font-weight:800;">{ann:.2f}%</div>'
                '</div>'

                '<div style="background:rgba(255,255,255,0.05); border-radius:5px; padding:7px 10px;">'
                '<div style="font-size:10px; color:#6b7280; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; margin-bottom:3px;">Gross P&amp;L</div>'
                '<div style="font-size:13px; color:#e2e8f0; font-weight:600;">Rs.{gross:,.2f}</div>'
                '</div>'

                '<div style="background:rgba(255,255,255,0.05); border-radius:5px; padding:7px 10px;">'
                '<div style="font-size:10px; color:#6b7280; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; margin-bottom:3px;">Transaction Cost</div>'
                '<div style="font-size:13px; color:#e2e8f0; font-weight:600;">Rs.{fric:,.2f}</div>'
                '</div>'

                '<div style="background:rgba(255,255,255,0.05); border-radius:5px; padding:7px 10px;">'
                '<div style="font-size:10px; color:#6b7280; font-weight:700; letter-spacing:0.06em; text-transform:uppercase; margin-bottom:3px;">Expiry</div>'
                '<div style="font-size:13px; color:#e2e8f0; font-weight:600;">{exp} ({days}d)</div>'
                '</div>'
                '</div>'

                '<div style="font-size:12px; color:#7fb3d3; padding:4px 0 0 0;">'
                '<span style="font-size:10px; color:#4b5563; font-weight:700;'
                ' text-transform:uppercase; letter-spacing:0.06em;">Execution: </span>'
                '{action}'
                '</div>'
                '</div>'
            ).format(
                bg=bg_col, bc=border_col, sc=sc, n=i+1,
                strat=opp["strategy"], asset=opp["asset"], badge=profit_badge,
                pc=pnl_color, pnl=opp["net_pnl"],
                typ=opp["type"], sp=sp,
                spot_val="{:,.2f}".format(opp["spot"]),
                gross=opp["gross"], fric=opp["friction"],
                exp=opp["expiry"].strftime("%d %b %Y"), days=opp["days"],
                ann=opp["ann_return"], action=opp["action"])

            st.markdown(card_html, unsafe_allow_html=True)

        # ── Comparison bar chart ───────────────────────────────────────────
        if len(opportunities) > 1:
            st.markdown("### 📊 Opportunity Comparison")
            labels    = ["{} {}".format(o["asset"], o["strategy"][:3]) for o in opportunities]
            net_vals  = [o["net_pnl"] for o in opportunities]
            ann_vals  = [o["ann_return"] for o in opportunities]
            colors    = ["#16a34a" if o["profitable"] else "#adb5bd" for o in opportunities]

            fig_scan = go.Figure()
            fig_scan.add_trace(go.Bar(
                name="Net P&L (₹)", x=labels, y=net_vals,
                marker_color=colors,
                text=["₹{:,.0f}".format(v) for v in net_vals],
                textposition="outside", yaxis="y1"))
            fig_scan.add_trace(go.Scatter(
                name="Ann. Return (%)", x=labels, y=ann_vals,
                mode="lines+markers+text",
                line=dict(color="#ff7f0e", width=2.5),
                marker=dict(size=8, color="#f59e0b"),
                text=["{:.1f}%".format(v) for v in ann_vals],
                textposition="top center",
                yaxis="y2"))
            fig_scan.update_layout(
                title="Net P&L & Annualised Return — All Scanned Opportunities",
                xaxis=dict(title="Strategy · Asset"),
                yaxis=dict(title=dict(text="Net P&L (₹)", font=dict(color="#16a34a")),
                           tickformat=",.0f"),
                yaxis2=dict(title=dict(text="Ann. Return (%)", font=dict(color="#f59e0b")),
                            overlaying="y", side="right", tickformat=".1f"),
                height=380, margin=dict(t=45, b=40, l=10, r=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                plot_bgcolor="#131c2b", paper_bgcolor="#0d1421", barmode="group")
            st.plotly_chart(fig_scan, use_container_width=True)

        # ── Exportable summary table ───────────────────────────────────────
        st.markdown("### 📥 Summary Table")
        tbl = pd.DataFrame([{
            "Rank":       i+1,
            "Strategy":   o["strategy"],
            "Asset":      o["asset"],
            "Type":       o["type"],
            "Spot":       "₹{:,.2f}".format(o["spot"]) if o["asset"] != "USD/INR" else "{:.4f}".format(o["spot"]),
            "Gap":        "{:.4f}".format(o["gap"]),
            "Gross P&L":  "₹{:,.2f}".format(o["gross"]),
            "Friction":   "₹{:,.2f}".format(o["friction"]),
            "Net P&L":    "₹{:,.2f}".format(o["net_pnl"]),
            "Ann. Return":"{:.2f}%".format(o["ann_return"]),
            "Expiry":     o["expiry"].strftime("%d %b %Y"),
            "Profitable": "✅" if o["profitable"] else "❌",
            "Action":     o["action"],
        } for i, o in enumerate(opportunities)])
        st.dataframe(tbl, hide_index=True, use_container_width=True)
        st.caption("Data is indicative. PCP uses ATM strike. Futures Basis uses estimated market price (+0.8% of fair). IRP uses USD 1,00,000 notional.")

    else:
        st.info("No opportunities found matching your filters. Try lowering the minimum profit threshold or adding more assets.")

    if st.session_state.show_metadata:
        with st.expander("ℹ️ Scanner Methodology", expanded=False):
            st.markdown("""
            **How the scanner works:**
            - **Put-Call Parity**: Uses ATM strike for each asset, computes gap = Spot − Synthetic, deducts STT + brokerage
            - **Futures Basis**: Computes fair futures price using Cost-of-Carry (F* = S·e^(rT)), compares to simulated market futures price
            - **Interest Rate Parity**: Uses live USD/INR spot from yfinance, India vs US rate differential, 90-day tenor
            - **Annualised Return**: (Net P&L / Capital Deployed) × (365 / Days to Expiry) × 100
            - **Capital deployed**: Spot price × lot size (1 lot per scan per asset)
            - Opportunities are sorted by Net P&L descending
            - ⚠️ Futures Basis uses an estimated futures price (+0.8% above fair). Use Tab 3 for actual market price.
            """)

# ══════════════════════════════════════════════════════════════════════════════
# TAB 1 — PUT-CALL PARITY ARBITRAGE
# ══════════════════════════════════════════════════════════════════════════════
with tab1:
    st.subheader("📐 Put-Call Parity Arbitrage")
    st.markdown(
        "**Theory:** For European options: `C − P = S₀ − K·e^(−rT)`  "
        "Any measurable deviation after transaction costs = risk-free profit."
    )

    col_a, col_b = st.columns([1, 2])
    with col_a:
        asset    = st.selectbox("Select Asset", list(LOT_SIZES.keys()), key="pcp_asset")
        num_lots = st.number_input("Number of Lots", min_value=1, value=1, step=1, key="pcp_lots")

    with st.spinner("📡 Fetching data for {}...".format(asset)):
        s0, calls_df, puts_df, nse_expiry, nse_expiries, fetch_error, data_source = get_market_data(asset)

    # ── EXPIRY DATE INPUT ──────────────────────────────────────────────────────
    st.markdown("#### 📅 Expiry Date")
    exp_col1, exp_col2, exp_col3 = st.columns([1.2, 1.2, 1.6])
    with exp_col1:
        today = datetime.date.today()
        # Next NSE monthly expiry = last Thursday of the month
        def last_thursday(year, month):
            import calendar
            cal = calendar.monthcalendar(year, month)
            thursdays = [w[3] for w in cal if w[3] != 0]
            return datetime.date(year, month, thursdays[-1])

        # Build next 4 monthly expiries
        suggested_expiries = []
        y, m = today.year, today.month
        for _ in range(4):
            exp = last_thursday(y, m)
            if exp > today:
                suggested_expiries.append(exp)
            m += 1
            if m > 12:
                m = 1; y += 1

        # If NSE API returned expiry string, parse it
        parsed_nse_expiry = None
        if nse_expiry:
            try:
                parsed_nse_expiry = datetime.datetime.strptime(nse_expiry, "%d-%b-%Y").date()
            except Exception:
                try:
                    parsed_nse_expiry = datetime.datetime.strptime(nse_expiry, "%Y-%m-%d").date()
                except Exception:
                    pass

        default_expiry = parsed_nse_expiry if parsed_nse_expiry else (suggested_expiries[0] if suggested_expiries else today + datetime.timedelta(days=30))
        expiry_date = st.date_input(
            "Expiry Date",
            value=default_expiry,
            min_value=today + datetime.timedelta(days=1),
            max_value=today + datetime.timedelta(days=365),
            help="Select the actual NSE expiry date for this contract",
            key="pcp_expiry"
        )

    with exp_col2:
        days_to_expiry = (expiry_date - today).days
        st.metric("Days to Expiry", "{} days".format(days_to_expiry))

    with exp_col3:
        if parsed_nse_expiry:
            st.success("✅ NSE expiry loaded: **{}**".format(nse_expiry))
        else:
            st.info("📅 Manually selected expiry. NSE monthly expiries are typically the last Thursday of each month.")

    t = days_to_expiry / 365.0

    # Status banner
    if data_source == "nse":
        st.success("✅ Live NSE option chain | Spot: ₹{:,.2f}".format(s0))
    elif data_source == "yf_spot":
        st.warning("⚠️ {}".format(fetch_error))
        st.markdown(
            '<div class="nse-link-box">📋 <strong>Get option prices from NSE:</strong> '
            '<a href="{}" target="_blank">Open {} Option Chain on NSE ↗</a><br>'
            'Enter ATM Call & Put LTP below.</div>'.format(NSE_CHAIN_URLS[asset], asset),
            unsafe_allow_html=True)
    else:
        st.error("⚠️ {}".format(fetch_error))
        st.markdown(
            '<div class="nse-link-box">📋 <a href="{}" target="_blank">Open {} Option Chain on NSE ↗</a></div>'.format(
                NSE_CHAIN_URLS[asset], asset), unsafe_allow_html=True)

    lot = LOT_SIZES[asset]
    total_units = num_lots * lot
    step = float(STRIKE_STEP[asset])

    def lookup_option_price(chain_df, target_strike):
        if chain_df.empty: return None
        mask = np.isclose(chain_df["strike"].values, target_strike, rtol=0, atol=step * 0.4)
        if not mask.any(): return None
        price = chain_df.loc[mask, "lastPrice"].values[0]
        vol   = chain_df.loc[mask, "volume"].values[0] if "volume" in chain_df.columns else np.nan
        oi    = chain_df.loc[mask, "openInterest"].values[0] if "openInterest" in chain_df.columns else np.nan
        if price > 0 and (pd.isna(vol) or vol > 0 or (not pd.isna(oi) and oi > 0)):
            return float(round(price, 2))
        return None

    p1, p2, p3 = st.columns(3)
    with p1:
        default_strike = float(round(s0 / step) * step)
        strike = st.number_input("Strike Price (₹)", value=default_strike, step=step, format="%.2f", key="pcp_strike_{}".format(asset))
    with p2:
        live_call    = lookup_option_price(calls_df, strike)
        call_default = live_call if live_call is not None else round(s0 * 0.025, 2)
        call_src     = "🟢 Live" if live_call is not None else "🟡 Enter manually"
        c_mkt = st.number_input("Call Price (₹)  {}".format(call_src),
                                value=float(call_default), min_value=0.01, step=0.5, format="%.2f", key="pcp_call_{}".format(asset))
    with p3:
        live_put    = lookup_option_price(puts_df, strike)
        put_default = live_put if live_put is not None else round(s0 * 0.018, 2)
        put_src     = "🟢 Live" if live_put is not None else "🟡 Enter manually"
        p_mkt = st.number_input("Put Price (₹)  {}".format(put_src),
                                value=float(put_default), min_value=0.01, step=0.5, format="%.2f", key="pcp_put_{}".format(asset))

    # ── CALCULATIONS ──────────────────────────────────────────────────────────
    pv_k            = strike * np.exp(-r_rate * t)
    synthetic_spot  = c_mkt - p_mkt + pv_k
    spread_per_unit = s0 - synthetic_spot
    fno_orders      = 2 * num_lots
    total_brokerage = brokerage * (fno_orders + 2)
    stt_spot        = s0 * total_units * 0.001
    stt_options     = (c_mkt + p_mkt) * total_units * 0.000625
    total_friction  = total_brokerage + stt_spot + stt_options
    gross_spread    = abs(spread_per_unit) * total_units
    arb_threshold   = s0 * (arb_threshold_pct / 100)

    if spread_per_unit > arb_threshold:
        signal_line, signal_color, strategy_desc, signal_type = \
            "✅ CONVERSION ARBITRAGE DETECTED", "#16a34a", "Buy Spot  ·  Buy Put  ·  Sell Call", "conversion"
        net_pnl = gross_spread - total_friction
    elif spread_per_unit < -arb_threshold:
        signal_line, signal_color, strategy_desc, signal_type = \
            "🔴 REVERSAL ARBITRAGE DETECTED", "#dc2626", "Short Spot  ·  Sell Put  ·  Buy Call", "reversal"
        net_pnl = gross_spread - total_friction
    else:
        signal_line, signal_color, strategy_desc, signal_type = \
            "⚪ MARKET IS EFFICIENT — No Arbitrage", "#6b7280", "No Action", "none"
        net_pnl = -total_friction

    pnl_profitable = net_pnl > 0

    # ── METRICS ROW ───────────────────────────────────────────────────────────
    st.markdown("---")
    ann_return_pcp = (net_pnl / max(s0 * total_units * margin_pct, 1)) * (365 / max(days_to_expiry, 1)) * 100

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Market Spot",       "₹{:,.2f}".format(s0))
    m2.metric("Synthetic Price",   "₹{:,.2f}".format(synthetic_spot))
    m3.metric("Gap / unit",        "₹{:.2f}".format(abs(spread_per_unit)))
    m4.metric("Total Friction",    "₹{:,.2f}".format(total_friction))
    m5.metric("Net P&L",           "₹{:,.2f}".format(net_pnl),
              delta="✅ Profitable" if pnl_profitable else "❌ Loss after costs",
              delta_color="normal" if pnl_profitable else "inverse")
    m6.metric("Ann. Return",       "{:.2f}%".format(ann_return_pcp),
              delta="{} days".format(days_to_expiry), delta_color="off")

    pulse_class = "signal-pulse-green" if signal_type == "conversion" else (
                   "signal-pulse-red"   if signal_type == "reversal" else "")
    st.markdown(
        '<div class="{pulse}" style="background:{c}; padding:16px; border-radius:12px; text-align:center; '
        'color:white; margin:12px 0; border: 2px solid rgba(255,255,255,0.2);">'
        '<h2 style="margin:0; font-size:22px; font-weight:900;">{s}</h2>'
        '<p style="margin:4px 0 0; font-size:14px; opacity:.9;">'
        'Strategy: <b>{d}</b> &nbsp;|&nbsp; Expiry: <b>{e}</b> &nbsp;|&nbsp; '
        '<b>{dte} days</b> &nbsp;|&nbsp; Ann. Return: <b>{ann:.2f}%</b></p></div>'.format(
            pulse=pulse_class, c=signal_color, s=signal_line, d=strategy_desc,
            e=expiry_date.strftime("%d %b %Y"), dte=days_to_expiry, ann=ann_return_pcp),
        unsafe_allow_html=True)


    # ── FEATURE 12: ALERT SYSTEM ─────────────────────────────────────────────
    alert_threshold = st.session_state.get("alert_threshold", 500)
    if signal_type != "none" and pnl_profitable and net_pnl >= alert_threshold:
        st.markdown(
            '''<div style="background:linear-gradient(135deg,#052e16,#14532d);
                border:3px solid #22c55e; border-radius:12px; padding:16px 24px;
                text-align:center; margin:8px 0;
                box-shadow: 0 0 30px rgba(34,197,94,0.4);"
                class="signal-pulse-green">
              <div style="font-size:28px;">🚨</div>
              <div style="font-size:20px;font-weight:900;color:#22c55e;">
                TRADE SIGNAL — EXECUTE NOW</div>
              <div style="font-size:14px;color:#86efac;margin-top:4px;">
                Net Profit ₹{pnl:,.2f} exceeds your alert threshold of ₹{thr:,.0f}
                &nbsp;|&nbsp; Ann. Return: {ann:.2f}%
                &nbsp;|&nbsp; Expiry: {exp}
              </div>
            </div>'''.format(
                pnl=net_pnl, thr=alert_threshold,
                ann=ann_return_pcp, exp=expiry_date.strftime("%d %b %Y")),
            unsafe_allow_html=True)
    elif signal_type != "none" and pnl_profitable:
        st.info("💡 Profitable opportunity found. Raise alert threshold in ⚙️ Settings to trigger the TRADE NOW banner.")

    if signal_type != "none" and not pnl_profitable:
        st.markdown('<div class="warning-box">⚠️ Gap detected but NOT profitable after costs. Do not trade.</div>',
                    unsafe_allow_html=True)

    # ── PROOF + CHART ─────────────────────────────────────────────────────────
    st.write("")
    col_proof, col_graph = st.columns([1, 1.5])

    with col_proof:
        st.subheader("📊 Execution Proof")
        st.markdown("**Strategy:** {}".format(strategy_desc))
        st.markdown("**Expiry Date:** {}  ·  **T = {:.4f} years**".format(
            expiry_date.strftime("%d %b %Y"), t))
        st.latex(r"C - P = S_0 - K \cdot e^{-rT}")
        st.latex(r"\text{Gap} = S_0 - \underbrace{(C - P + K e^{-rT})}_{\text{Synthetic Fair Price}}")
        cost_df = pd.DataFrame({
            "Item": ["Brokerage ({} orders)".format(fno_orders + 2),
                     "STT on Spot (0.1%)", "STT on Options (0.0625%)", "Total Friction"],
            "Amount (₹)": ["₹{:,.2f}".format(total_brokerage), "₹{:,.2f}".format(stt_spot),
                           "₹{:,.2f}".format(stt_options),      "₹{:,.2f}".format(total_friction)]
        })
        st.dataframe(cost_df, hide_index=True, use_container_width=True)
        st.metric("Net Profit (after all costs)", "₹{:,.2f}".format(net_pnl),
                  delta="Profitable ✅" if pnl_profitable else "Loss ❌",
                  delta_color="normal" if pnl_profitable else "inverse")
        st.caption("Across {:,} units ({} lot{} × {})".format(
            total_units, num_lots, "s" if num_lots > 1 else "", lot))


    with col_graph:
        prices = np.linspace(s0 * 0.75, s0 * 1.25, 300)
        if signal_type == "conversion":
            spot_pnl = (prices - s0) * total_units
            put_pnl  = (np.maximum(strike - prices, 0) - p_mkt) * total_units
            call_pnl = (c_mkt - np.maximum(prices - strike, 0)) * total_units
        elif signal_type == "reversal":
            spot_pnl = (s0 - prices) * total_units
            put_pnl  = (p_mkt - np.maximum(strike - prices, 0)) * total_units
            call_pnl = (np.maximum(prices - strike, 0) - c_mkt) * total_units
        else:
            spot_pnl = put_pnl = call_pnl = np.zeros_like(prices)

        net_locked = np.full(len(prices), net_pnl)
        net_pad    = max(abs(net_pnl) * 5, 500)

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=prices, y=spot_pnl, mode="lines", name="Spot Leg",
                                 line=dict(color="#1f77b4", width=1.5, dash="dot"), opacity=0.5, yaxis="y1"))
        fig.add_trace(go.Scatter(x=prices, y=put_pnl, mode="lines", name="Put Leg",
                                 line=dict(color="#ff7f0e", width=1.5, dash="dot"), opacity=0.5, yaxis="y1"))
        fig.add_trace(go.Scatter(x=prices, y=call_pnl, mode="lines", name="Call Leg",
                                 line=dict(color="#9467bd", width=1.5, dash="dot"), opacity=0.5, yaxis="y1"))
        fig.add_trace(go.Scatter(x=prices, y=net_locked, mode="lines", name="Net P&L (locked)",
                                 line=dict(color=signal_color, width=3.5), yaxis="y2"))
        fig.add_shape(type="line", x0=prices[0], x1=prices[-1], y0=0, y1=0,
                      line=dict(color="gray", width=1, dash="dash"), yref="y2")
        fig.add_vline(x=s0, line_dash="dash", line_color="#333", line_width=1,
                      annotation_text="Spot ₹{:,.0f}".format(s0), annotation_position="top right")
        fig.update_layout(
            title="Payoff at Expiry ({}) — {} days".format(expiry_date.strftime("%d %b %Y"), days_to_expiry),
            xaxis=dict(title="Spot Price at Expiry (₹)", tickformat=",.0f", showgrid=True, gridcolor="#1e3050"),
            yaxis=dict(title=dict(text="Leg P&L (₹)", font=dict(color="#555")),
                       tickformat=",.0f", showgrid=False),
            yaxis2=dict(title=dict(text="Net P&L (₹)", font=dict(color=signal_color)),
                        tickformat=",.0f", overlaying="y", side="right",
                        range=[-net_pad, net_pad], showgrid=True, gridcolor="#1e3050"),
            height=370, margin=dict(t=45, b=40, l=10, r=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified", plot_bgcolor="#131c2b", paper_bgcolor="#0d1421")
        st.plotly_chart(fig, use_container_width=True)
        st.caption("📌 Dotted = individual legs (left axis). Solid = Net P&L after costs (right axis). The flat line proves the arbitrage is locked.")

    # ── SCENARIO TABLE ────────────────────────────────────────────────────────
    st.divider()
    st.subheader("📉 Expiry Scenario Analysis")
    st.caption("Net P&L is identical across all expiry prices — proving the payoff is fully locked at entry.")
    scenarios = {"Bear (−15%)": s0*0.85, "Bear (−10%)": s0*0.90, "At Strike": strike,
                 "At Money": s0, "Bull (+10%)": s0*1.10, "Bull (+15%)": s0*1.15}
    rows = []
    for label, ep in scenarios.items():
        if signal_type == "conversion":
            sl = (ep - s0)*total_units; pl = (max(strike-ep,0)-p_mkt)*total_units; cl = (c_mkt-max(ep-strike,0))*total_units
        elif signal_type == "reversal":
            sl = (s0-ep)*total_units;  pl = (p_mkt-max(strike-ep,0))*total_units; cl = (max(ep-strike,0)-c_mkt)*total_units
        else:
            sl = pl = cl = 0.0
        gross = gross_spread if signal_type != "none" else 0.0
        rows.append({"Scenario": label, "Expiry Price": "₹{:,.0f}".format(ep),
                     "Spot Leg (₹)": "₹{:,.2f}".format(sl), "Put Leg (₹)": "₹{:,.2f}".format(pl),
                     "Call Leg (₹)": "₹{:,.2f}".format(cl),
                     "Gross P&L (₹)": "₹{:,.2f}".format(gross),
                     "Friction (₹)": "−₹{:,.2f}".format(total_friction),
                     "Net P&L (₹)": "₹{:,.2f}".format(gross - total_friction)})
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    st.info("**Gross P&L = ₹{:,.2f}** (gap × units).  **Net P&L = ₹{:,.2f}** (Gross − Friction). "
            "Identical in every row — the arbitrage is locked at inception.".format(gross_spread, net_pnl))



# ══════════════════════════════════════════════════════════════════════════════
# TAB 2 — INTEREST RATE PARITY (IRP)
# ══════════════════════════════════════════════════════════════════════════════
with tab2:
    st.subheader("🌍 Covered Interest Rate Parity (CIRP) Arbitrage")
    st.markdown("""
    **Theory — Covered IRP:** The forward exchange rate between two currencies must satisfy:

    `F = S × e^((r_d − r_f) × T)`

    where **F** = theoretical forward rate, **S** = spot USD/INR rate, **r_d** = domestic (India) rate,
    **r_f** = foreign (US) rate, **T** = tenor in years.

    If the **market forward rate ≠ theoretical forward**, a covered arbitrage opportunity exists.
    """)

    with st.expander("📖 How IRP Arbitrage Works", expanded=False):
        st.markdown("""
        **If Market Forward > Theoretical Forward (Forward is too expensive):**
        1. Borrow USD at US risk-free rate for T years
        2. Convert USD → INR at spot rate S
        3. Invest INR at Indian risk-free rate for T years
        4. Enter forward contract to sell INR → USD at market forward F_mkt
        5. At maturity: repay USD loan, profit = (F_mkt − F_theoretical) × notional

        **If Market Forward < Theoretical Forward (Forward is too cheap):**
        1. Borrow INR at Indian rate
        2. Convert INR → USD at spot rate S
        3. Invest USD at US rate
        4. Enter forward contract to buy INR → sell USD at F_mkt
        5. At maturity: repay INR loan, profit = (F_theoretical − F_mkt) × notional
        """)

    irp_c1, irp_c2, irp_c3 = st.columns(3)
    with irp_c1:
        spot_usd_inr = get_forex_rate()
        st.metric("Live USD/INR Spot", "{:.4f}".format(spot_usd_inr), help="From yfinance (USDINR=X)")
        s_fx = st.number_input("USD/INR Spot Rate", value=float(spot_usd_inr),
                               min_value=60.0, max_value=110.0, step=0.01, format="%.4f", key="irp_spot")
    with irp_c2:
        r_us = st.slider("US Risk-Free Rate (%)", 1.0, 8.0, 5.25, step=0.25, key="irp_rus") / 100
        r_in = st.slider("India Risk-Free Rate (%)", 4.0, 10.0, 6.75, step=0.25, key="irp_rin") / 100
    with irp_c3:
        irp_expiry = st.date_input("Forward Contract Maturity",
                                   value=today + datetime.timedelta(days=90),
                                   min_value=today + datetime.timedelta(days=1),
                                   max_value=today + datetime.timedelta(days=730),
                                   key="irp_expiry")
        irp_days   = (irp_expiry - today).days
        irp_T      = irp_days / 365.0
        st.metric("Tenor", "{} days ({:.3f}y)".format(irp_days, irp_T))

    notional_usd = st.number_input("Notional (USD)", value=100000.0, min_value=1000.0, step=10000.0,
                                   format="%.0f", key="irp_notional",
                                   help="Size of the arbitrage trade in USD")
    f_mkt = st.number_input("Market Forward Rate (USD/INR)",
                            value=float(round(s_fx * np.exp((r_in - r_us) * irp_T) + 0.5, 4)),
                            min_value=60.0, max_value=120.0, step=0.01, format="%.4f", key="irp_fmkt",
                            help="The actual forward rate quoted by your bank/broker")

    # Calculations
    f_theory  = s_fx * np.exp((r_in - r_us) * irp_T)
    irp_gap   = f_mkt - f_theory
    irp_gap_pct = (irp_gap / f_theory) * 100

    # P&L in INR
    notional_inr   = notional_usd * s_fx
    irp_gross_inr  = abs(irp_gap) * notional_usd
    irp_brokerage  = brokerage * 4   # 4 transactions: borrow, convert, invest, forward
    irp_friction   = irp_brokerage   # simplified (no STT on forex)
    irp_net_inr    = irp_gross_inr - irp_friction
    irp_net_usd    = irp_net_inr / s_fx

    # Signal
    irp_threshold = f_theory * (arb_threshold_pct / 100)
    if irp_gap > irp_threshold:
        irp_signal = "🔴 FORWARD TOO EXPENSIVE — Borrow USD · Invest INR · Sell Forward"
        irp_color  = "#dc2626"
    elif irp_gap < -irp_threshold:
        irp_signal = "✅ FORWARD TOO CHEAP — Borrow INR · Invest USD · Buy Forward"
        irp_color  = "#16a34a"
    else:
        irp_signal = "⚪ IRP HOLDS — No Covered Arbitrage Opportunity"
        irp_color  = "#6b7280"

    st.markdown("---")
    i1, i2, i3, i4, i5 = st.columns(5)
    i1.metric("Spot USD/INR",     "{:.4f}".format(s_fx))
    i2.metric("Theoretical Fwd",  "{:.4f}".format(f_theory))
    i3.metric("Market Fwd",       "{:.4f}".format(f_mkt))
    i4.metric("Fwd Gap",          "{:.4f} ({:.3f}%)".format(irp_gap, irp_gap_pct))
    i5.metric("Net Profit (INR)", "₹{:,.2f}".format(irp_net_inr),
              delta="≈ USD {:,.2f}".format(irp_net_usd), delta_color="off")

    st.markdown(
        '<div style="background:{c}; padding:14px; border-radius:10px; text-align:center; color:white; margin:12px 0;">'
        '<h2 style="margin:0; font-size:20px;">{s}</h2>'
        '<p style="margin:4px 0 0; font-size:14px; opacity:.9;">Notional: USD {n:,.0f} | Maturity: {e} ({d} days)</p>'
        '</div>'.format(c=irp_color, s=irp_signal, n=notional_usd,
                        e=irp_expiry.strftime("%d %b %Y"), d=irp_days),
        unsafe_allow_html=True)

    st.markdown("#### 📐 Detailed Calculation")
    irp_calc = pd.DataFrame({
        "Step": ["Spot Rate (S)", "India Rate (r_d)", "US Rate (r_f)",
                 "Tenor T (years)", "Theoretical Forward = S·e^((r_d−r_f)·T)",
                 "Market Forward (F_mkt)", "Forward Gap (F_mkt − F_theory)",
                 "Notional (USD)", "Gross Profit = |Gap| × Notional (INR)",
                 "Transaction Costs (INR)", "Net Profit (INR)", "Net Profit (USD)"],
        "Value": [
            "{:.4f}".format(s_fx), "{:.2f}%".format(r_in*100), "{:.2f}%".format(r_us*100),
            "{:.4f}y ({} days)".format(irp_T, irp_days),
            "{:.4f}".format(f_theory), "{:.4f}".format(f_mkt),
            "{:.4f} ({:.3f}%)".format(irp_gap, irp_gap_pct),
            "USD {:,.0f}".format(notional_usd),
            "₹{:,.2f}".format(irp_gross_inr),
            "₹{:,.2f}".format(irp_friction),
            "₹{:,.2f}".format(irp_net_inr),
            "USD {:,.2f}".format(irp_net_usd),
        ]
    })
    st.dataframe(irp_calc, hide_index=True, use_container_width=True)

    # Forward rate sensitivity chart
    st.markdown("#### 📊 Forward Gap Sensitivity — Net P&L vs Market Forward Rate")
    fwd_range  = np.linspace(f_theory * 0.98, f_theory * 1.02, 200)
    pnl_range  = [abs(fm - f_theory) * notional_usd - irp_friction for fm in fwd_range]
    fig_irp = go.Figure()
    fig_irp.add_trace(go.Scatter(
        x=fwd_range, y=pnl_range, mode="lines",
        line=dict(color="#1f77b4", width=2.5),
        fill="tozeroy",
        fillcolor="rgba(31,119,180,0.12)",
        name="Net Profit (INR)"))
    fig_irp.add_vline(x=f_theory,  line_dash="dash", line_color="green",  annotation_text="Theoretical Fwd")
    fig_irp.add_vline(x=f_mkt,     line_dash="dash", line_color="red",    annotation_text="Market Fwd")
    fig_irp.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
    fig_irp.update_layout(
        title="Net IRP Arbitrage P&L (INR) vs Market Forward Rate",
        xaxis=dict(title="Market Forward Rate (USD/INR)", tickformat=".4f"),
        yaxis=dict(title="Net Profit (₹)", tickformat=",.0f"),
        height=320, margin=dict(t=40,b=30,l=10,r=10),
        plot_bgcolor="#131c2b", paper_bgcolor="#0d1421", showlegend=False)
    st.plotly_chart(fig_irp, use_container_width=True)
    st.caption("Green = Theoretical forward (no-arbitrage). Red = current market forward. Width of gap = arbitrage opportunity size.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 3 — FUTURES BASIS (CASH & CARRY)
# ══════════════════════════════════════════════════════════════════════════════
with tab3:
    st.subheader("📦 Futures Basis — Cash & Carry Arbitrage")
    st.markdown("""
    **Theory — Cost of Carry:** The fair futures price is:

    `F* = S × e^((r + d) × T)`

    where **r** = risk-free rate, **d** = storage/holding cost (net of dividends), **T** = time to expiry.

    - **If F_mkt > F_fair** → **Cash & Carry**: Buy spot, sell futures, deliver at expiry
    - **If F_mkt < F_fair** → **Reverse Cash & Carry**: Short spot, buy futures, accept delivery
    """)

    with st.expander("📖 How Futures Basis Arbitrage Works", expanded=False):
        st.markdown("""
        **Cash & Carry (Futures overpriced):**
        1. Borrow money at risk-free rate for T years
        2. Buy the underlying spot at price S
        3. Sell futures contract at F_mkt (above fair value F*)
        4. At expiry: deliver spot into futures, repay loan
        5. Profit = F_mkt − S·e^(rT) per unit (the basis mispricing)

        **Reverse Cash & Carry (Futures underpriced):**
        1. Short sell the underlying spot at S
        2. Invest short-sale proceeds at risk-free rate
        3. Buy futures at F_mkt (below fair value F*)
        4. At expiry: take delivery via futures to close short
        5. Profit = S·e^(rT) − F_mkt per unit
        """)

    fb_c1, fb_c2 = st.columns(2)
    with fb_c1:
        fb_asset   = st.selectbox("Select Asset", list(LOT_SIZES.keys()), key="fb_asset")
        fb_lots    = st.number_input("Number of Lots", min_value=1, value=1, step=1, key="fb_lots")
        holding_cost_pct = st.slider("Holding Cost / Dividend Yield (%)", -3.0, 5.0, 0.0, step=0.1,
                                     help="Annual storage or holding cost. Negative = dividend yield (reduces fair futures price)",
                                     key="fb_hold")
    with fb_c2:
        fb_expiry  = st.date_input("Futures Expiry Date",
                                   value=last_thursday(today.year, today.month) if last_thursday(today.year, today.month) > today
                                   else last_thursday(today.year, today.month + 1 if today.month < 12 else 1),
                                   min_value=today + datetime.timedelta(days=1),
                                   max_value=today + datetime.timedelta(days=365),
                                   key="fb_expiry")
        fb_days    = (fb_expiry - today).days
        fb_T       = fb_days / 365.0
        st.metric("Days to Expiry", "{} days ({:.4f}y)".format(fb_days, fb_T))

    with st.spinner("Fetching spot for {}...".format(fb_asset)):
        fb_s0_data = get_market_data(fb_asset)
        fb_s0      = fb_s0_data[0]

    fb_spot    = st.number_input("Spot Price (₹)", value=float(fb_s0), min_value=1.0, step=1.0,
                                 format="%.2f", key="fb_spot_{}".format(fb_asset))
    r_carry    = r_rate + (holding_cost_pct / 100)
    fb_fair    = fb_spot * np.exp(r_carry * fb_T)
    fb_lot_sz  = LOT_SIZES[fb_asset]
    fb_units   = fb_lots * fb_lot_sz

    fb_mkt = st.number_input("Market Futures Price (₹)",
                             value=float(round(fb_fair + 50, 2)),
                             min_value=1.0, step=1.0, format="%.2f", key="fb_fmkt_{}".format(fb_asset),
                             help="The actual futures price quoted on NSE/BSE")

    # Calculations
    fb_basis    = fb_mkt - fb_fair           # + = futures rich, − = futures cheap
    fb_basis_pct = (fb_basis / fb_fair) * 100
    fb_threshold = fb_fair * (arb_threshold_pct / 100)

    fb_gross    = abs(fb_basis) * fb_units
    fb_brokerage = brokerage * 4             # spot buy/sell + futures buy/sell
    fb_stt_spot = fb_spot * fb_units * 0.001
    fb_friction  = fb_brokerage + fb_stt_spot
    fb_net       = fb_gross - fb_friction
    fb_profitable = fb_net > 0

    if fb_basis > fb_threshold:
        fb_signal = "✅ CASH & CARRY — Buy Spot · Sell Futures · Deliver at Expiry"
        fb_color  = "#16a34a"
        fb_strategy = "Cash & Carry"
    elif fb_basis < -fb_threshold:
        fb_signal = "🔴 REVERSE CASH & CARRY — Short Spot · Buy Futures · Accept Delivery"
        fb_color  = "#dc2626"
        fb_strategy = "Reverse Cash & Carry"
    else:
        fb_signal = "⚪ BASIS FAIR — No Futures Arbitrage Opportunity"
        fb_color  = "#6b7280"
        fb_strategy = "No Trade"

    st.markdown("---")
    f1, f2, f3, f4, f5, f6 = st.columns(6)
    f1.metric("Spot Price",    "₹{:,.2f}".format(fb_spot))
    f2.metric("Fair Futures",  "₹{:,.2f}".format(fb_fair))
    f3.metric("Market Futures","₹{:,.2f}".format(fb_mkt))
    f4.metric("Basis",         "₹{:.2f} ({:.2f}%)".format(fb_basis, fb_basis_pct))
    f5.metric("Friction",      "₹{:,.2f}".format(fb_friction))
    f6.metric("Net P&L",       "₹{:,.2f}".format(fb_net),
              delta="Profitable ✅" if fb_profitable else "Loss ❌",
              delta_color="normal" if fb_profitable else "inverse")

    st.markdown(
        '<div style="background:{c}; padding:14px; border-radius:10px; text-align:center; color:white; margin:12px 0;">'
        '<h2 style="margin:0; font-size:20px;">{s}</h2>'
        '<p style="margin:4px 0 0; font-size:14px; opacity:.9;">Strategy: {st} | Expiry: {e} ({d} days)</p>'
        '</div>'.format(c=fb_color, s=fb_signal, st=fb_strategy,
                        e=fb_expiry.strftime("%d %b %Y"), d=fb_days),
        unsafe_allow_html=True)

    if fb_basis != 0 and not fb_profitable:
        st.markdown('<div class="warning-box">⚠️ Basis gap detected but costs exceed profit. Do not trade.</div>',
                    unsafe_allow_html=True)

    st.markdown("#### 📐 Detailed Calculation")
    fb_table = pd.DataFrame({
        "Parameter": ["Spot Price (S)", "Risk-Free Rate (r)", "Holding Cost/Dividend (d)",
                      "Carry Rate = r + d", "Time to Expiry T",
                      "Fair Futures F* = S·e^(carry×T)",
                      "Market Futures Price (F_mkt)", "Basis = F_mkt − F*",
                      "Total Units (lots × lot size)",
                      "Gross Profit = |Basis| × Units",
                      "Brokerage (4 orders)", "STT on Spot",
                      "Total Friction", "Net Profit"],
        "Value": [
            "₹{:,.2f}".format(fb_spot), "{:.2f}%".format(r_rate*100),
            "{:.2f}%".format(holding_cost_pct), "{:.2f}%".format(r_carry*100),
            "{} days ({:.4f}y)".format(fb_days, fb_T),
            "₹{:,.2f}".format(fb_fair), "₹{:,.2f}".format(fb_mkt),
            "₹{:.2f} ({:.3f}%)".format(fb_basis, fb_basis_pct),
            "{:,}".format(fb_units),
            "₹{:,.2f}".format(fb_gross),
            "₹{:,.2f}".format(fb_brokerage), "₹{:,.2f}".format(fb_stt_spot),
            "₹{:,.2f}".format(fb_friction),
            "₹{:,.2f}".format(fb_net),
        ]
    })
    st.dataframe(fb_table, hide_index=True, use_container_width=True)

    # Basis decay chart — shows convergence to zero at expiry
    st.markdown("#### 📊 Futures Basis Decay to Zero at Expiry")
    days_arr  = np.arange(fb_days, 0, -1)
    T_arr     = days_arr / 365.0
    fair_arr  = fb_spot * np.exp(r_carry * T_arr)
    basis_arr = fb_mkt - fair_arr          # basis decays as fair price rises to meet futures
    pnl_arr   = np.where(basis_arr > 0,
                         (basis_arr * fb_units) - fb_friction,
                         (abs(basis_arr) * fb_units) - fb_friction)

    fig_fb = go.Figure()
    fig_fb.add_trace(go.Scatter(x=days_arr[::-1], y=fair_arr[::-1], mode="lines",
                                name="Fair Futures F*", line=dict(color="#16a34a", width=2)))
    fig_fb.add_trace(go.Scatter(x=[fb_days, 0], y=[fb_mkt, fb_mkt], mode="lines",
                                name="Market Futures (entry)", line=dict(color="#dc2626", width=2, dash="dash")))
    fig_fb.add_trace(go.Scatter(x=days_arr[::-1], y=basis_arr[::-1], mode="lines",
                                name="Basis (Fmkt − F*)", line=dict(color="#ff7f0e", width=1.5, dash="dot"),
                                yaxis="y2"))
    fig_fb.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1, yref="y2")
    fig_fb.update_layout(
        title="Basis Decay: Fair Futures Converges to Market Price at Expiry",
        xaxis=dict(title="Days Remaining to Expiry", autorange="reversed"),
        yaxis=dict(title=dict(text="Price (₹)", font=dict(color="#16a34a")), tickformat=",.2f"),
        yaxis2=dict(title=dict(text="Basis (₹)", font=dict(color="#ff7f0e")),
                    overlaying="y", side="right", tickformat=",.2f"),
        height=320, margin=dict(t=40,b=30,l=10,r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="#131c2b", paper_bgcolor="#0d1421")
    st.plotly_chart(fig_fb, use_container_width=True)
    st.caption("As time passes, F* rises (cost of carry accumulates) and converges to F_mkt at expiry. "
               "The basis (orange dotted) decays to zero — this convergence locks in the arbitrage profit.")


# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — SETTINGS & CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
with tab4:
    st.subheader("⚙️ Settings & Configuration")
    st.markdown("Configure transaction costs, detection thresholds, and display preferences. "
                "All settings persist across tabs within this session.")

    cfg1, cfg2 = st.columns(2)

    # ── TRANSACTION COSTS ─────────────────────────────────────────────────────
    with cfg1:
        st.markdown("#### 💸 Transaction Costs")
        st.caption("As percentage of trade value. Applied in scanner and individual strategy tabs.")

        new_tc_equity  = st.number_input("Equity / Spot Trading (%)",
                                         value=float(st.session_state.tc_equity),
                                         min_value=0.0, max_value=1.0, step=0.005,
                                         format="%.4f", key="cfg_tc_eq",
                                         help="STT on equity delivery: 0.1% buy side = 0.05% round-trip equiv")
        new_tc_options = st.number_input("Options Trading (%)",
                                         value=float(st.session_state.tc_options),
                                         min_value=0.0, max_value=1.0, step=0.005,
                                         format="%.4f", key="cfg_tc_opt",
                                         help="STT on options sell side: 0.0625%")
        new_tc_futures = st.number_input("Futures Trading (%)",
                                         value=float(st.session_state.tc_futures),
                                         min_value=0.0, max_value=1.0, step=0.001,
                                         format="%.4f", key="cfg_tc_fut",
                                         help="STT on futures: 0.0125% sell side")
        new_tc_fx      = st.number_input("FX / Forex Trading (%)",
                                         value=float(st.session_state.tc_fx_spot),
                                         min_value=0.0, max_value=1.0, step=0.001,
                                         format="%.4f", key="cfg_tc_fx",
                                         help="Bank spread + conversion charges")
        new_brokerage  = st.number_input("Flat Brokerage per Order (₹)",
                                         value=float(st.session_state.brokerage_flat),
                                         min_value=0.0, max_value=100.0, step=5.0,
                                         key="cfg_brok",
                                         help="₹20 = Zerodha, ₹0 = no brokerage model")

        st.markdown("**Borrowing / Funding Spread**")
        new_borrow_spread = st.slider("Borrowing Spread above Risk-Free (%)",
                                      0.0, 3.0, 0.5, step=0.1, key="cfg_borrow",
                                      help="Additional cost when borrowing for Cash & Carry or IRP")

    # ── DETECTION THRESHOLDS ──────────────────────────────────────────────────
    with cfg2:
        st.markdown("#### 🎯 Detection Thresholds")
        st.caption("Minimum criteria for an opportunity to trigger a signal.")

        st.markdown("**Put-Call Parity**")
        new_pcp_min_profit = st.number_input("PCP Minimum Net Profit (₹)",
                                              value=float(st.session_state.pcp_min_profit),
                                              min_value=0.0, step=5.0, key="cfg_pcp_profit")
        new_pcp_min_dev    = st.slider("PCP Minimum Gap (% of Spot)",
                                       0.01, 1.0, float(st.session_state.pcp_min_dev),
                                       step=0.01, key="cfg_pcp_dev",
                                       help="Smaller = more sensitive, more noise")

        st.markdown("**Futures Basis**")
        new_fb_min_profit  = st.number_input("Futures Basis Minimum Net Profit (₹)",
                                              value=float(st.session_state.fb_min_profit),
                                              min_value=0.0, step=5.0, key="cfg_fb_profit")
        new_fb_min_dev     = st.slider("Futures Min Basis Deviation (% of Fair)",
                                       0.01, 1.0, float(st.session_state.fb_min_dev),
                                       step=0.01, key="cfg_fb_dev")

        st.markdown("**Interest Rate Parity**")
        new_irp_min_profit = st.number_input("IRP Minimum Net Profit (₹)",
                                              value=float(st.session_state.irp_min_profit),
                                              min_value=0.0, step=50.0, key="cfg_irp_profit")
        new_irp_min_dev    = st.slider("IRP Min Forward Deviation (% of Theoretical)",
                                       0.01, 1.0, float(st.session_state.irp_min_dev),
                                       step=0.01, key="cfg_irp_dev")

    st.divider()

    # ── DISPLAY & DATA SETTINGS ───────────────────────────────────────────────
    ds1, ds2 = st.columns(2)
    with ds1:
        st.markdown("#### 🔄 Auto-Refresh")
        new_auto_refresh = st.checkbox("Enable Auto-Refresh",
                                        value=bool(st.session_state.auto_refresh),
                                        key="cfg_autoref",
                                        help="Automatically re-runs the app at set interval")
        new_refresh_interval = st.slider("Refresh Interval (seconds)",
                                          10, 120, int(st.session_state.refresh_interval),
                                          step=10, key="cfg_interval",
                                          disabled=not new_auto_refresh)

    with ds2:
        st.markdown("#### 🖥️ Display Settings")
        new_show_metadata = st.checkbox("Show Scanner Methodology",
                                         value=bool(st.session_state.show_metadata),
                                         key="cfg_meta")
        new_margin_pct    = st.slider("Margin Requirement (%)", 10, 40,
                                       int(st.session_state.margin_pct),
                                       key="cfg_margin",
                                       help="Used to calculate Capital Required in PCP tab")

        st.markdown("**🚨 Alert Threshold**")
        new_alert_thr     = st.number_input("Minimum Net P&L to trigger TRADE NOW banner (₹)",
                                             value=float(st.session_state.get("alert_threshold", 500)),
                                             min_value=0.0, step=100.0, key="cfg_alert",
                                             help="Shows a flashing alert banner when Net P&L exceeds this value")

    st.divider()

    # ── SAVE BUTTON ───────────────────────────────────────────────────────────
    save_col, reset_col, _ = st.columns([1, 1, 3])
    with save_col:
        if st.button("💾 Save Settings", type="primary", use_container_width=True):
            st.session_state.tc_equity         = new_tc_equity
            st.session_state.tc_options        = new_tc_options
            st.session_state.tc_futures        = new_tc_futures
            st.session_state.tc_fx_spot        = new_tc_fx
            st.session_state.brokerage_flat    = new_brokerage
            st.session_state.pcp_min_profit    = new_pcp_min_profit
            st.session_state.pcp_min_dev       = new_pcp_min_dev
            st.session_state.fb_min_profit     = new_fb_min_profit
            st.session_state.fb_min_dev        = new_fb_min_dev
            st.session_state.irp_min_profit    = new_irp_min_profit
            st.session_state.irp_min_dev       = new_irp_min_dev
            st.session_state.auto_refresh      = new_auto_refresh
            st.session_state.refresh_interval  = new_refresh_interval
            st.session_state.show_metadata     = new_show_metadata
            st.session_state.margin_pct        = new_margin_pct
            st.session_state.alert_threshold   = new_alert_thr
            st.success("✅ Settings saved! All tabs will use updated values.")

    with reset_col:
        if st.button("🔄 Reset Defaults", use_container_width=True):
            keys_to_clear = ["tc_equity","tc_options","tc_futures","tc_fx_spot",
                             "brokerage_flat","pcp_min_profit","pcp_min_dev",
                             "fb_min_profit","fb_min_dev","irp_min_profit","irp_min_dev",
                             "auto_refresh","refresh_interval","show_metadata",
                             "margin_pct","iv_pct","r_rate_pct","arb_threshold_pct"]
            for k in keys_to_clear:
                if k in st.session_state:
                    del st.session_state[k]
            st.rerun()

    st.divider()

    # ── CURRENT CONFIG SUMMARY ────────────────────────────────────────────────
    st.markdown("#### 📋 Current Configuration Summary")
    config_text = """**Transaction Costs:**
- Equity/Spot: {tc_eq:.3f}%
- Options: {tc_opt:.3f}%
- Futures: {tc_fut:.3f}%
- FX/Forex: {tc_fx:.3f}%
- Flat Brokerage: ₹{brok:.0f} per order

**Detection Thresholds:**
- PCP Min Profit: ₹{pcp_p:.0f} | Min Gap: {pcp_d:.2f}%
- Futures Basis Min Profit: ₹{fb_p:.0f} | Min Basis: {fb_d:.2f}%
- IRP Min Profit: ₹{irp_p:.0f} | Min Fwd Dev: {irp_d:.2f}%

**Display Settings:**
- Margin Requirement: {margin}%
- Auto-Refresh: {ar} ({ari}s interval)
- Show Methodology: {meta}""".format(
        tc_eq=st.session_state.tc_equity,
        tc_opt=st.session_state.tc_options,
        tc_fut=st.session_state.tc_futures,
        tc_fx=st.session_state.tc_fx_spot,
        brok=st.session_state.brokerage_flat,
        pcp_p=st.session_state.pcp_min_profit,
        pcp_d=st.session_state.pcp_min_dev,
        fb_p=st.session_state.fb_min_profit,
        fb_d=st.session_state.fb_min_dev,
        irp_p=st.session_state.irp_min_profit,
        irp_d=st.session_state.irp_min_dev,
        margin=st.session_state.margin_pct,
        ar="ON" if st.session_state.auto_refresh else "OFF",
        ari=st.session_state.refresh_interval,
        meta="Enabled" if st.session_state.show_metadata else "Disabled")
    st.code(config_text, language=None)
    st.caption("⚠️ Settings are session-specific and reset when you close the browser.")

    # ── AUTO REFRESH LOGIC ────────────────────────────────────────────────────
    if st.session_state.auto_refresh:
        import time
        time.sleep(st.session_state.refresh_interval)
        st.rerun()

# ══════════════════════════════════════════════════════════════════════════════
# TAB 6 — DOCUMENTATION
# ══════════════════════════════════════════════════════════════════════════════
with tab5:
    st.markdown("""
    <div style="text-align:center; padding:20px 0 10px;">
      <div style="font-size:48px;">📚</div>
      <h1 style="color:#f59e0b; font-weight:900; margin:0;">Documentation</h1>
      <p style="color:#94a3b8;">Complete guide to the Cross-Asset Arbitrage Monitor</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # About
    doc_c1, doc_c2 = st.columns([2, 1])
    with doc_c1:
        st.markdown("""
### 🏛️ About This Project
The **Cross-Asset Arbitrage Opportunity Monitor** is a real-time financial dashboard
that detects mispricing across options and futures markets by checking fundamental
parity relationships. When market prices deviate from theoretical fair values,
the dashboard calculates the arbitrage profit and provides step-by-step execution instructions.

**Key Features:**
- ✅ Put-Call Parity arbitrage detection
- ✅ Futures Basis (Cost-of-Carry) arbitrage detection
- ✅ Covered Interest Rate Parity (CIRP) detection
- ✅ Cross-Market Statistical Spread Arbitrage
- ✅ Live market data via yfinance (spot prices)
- ✅ Option Greeks (Delta, Gamma, Theta, Vega, Rho) via Black-Scholes-Merton
- ✅ Historical gap analysis and sensitivity analysis
- ✅ Automated profit calculation including all transaction costs
- ✅ Step-by-step execution strategy for each opportunity
        """)

    with doc_c2:
        st.markdown("""
### 👥 Project Team
**Institution:** IIT Roorkee

**Department:** Management Studies

**Course:** Financial Engineering

**Team:** Group 4

**Supervisor:** Financial Engineering Faculty

---
**🔗 Live Dashboard:**
arbitrage-monitor-anchalfeproject.streamlit.app

**📦 GitHub:**
github.com/[your-username]/arbitrage-monitor
        """)

    st.markdown("---")

    # Strategies
    st.markdown("## 📐 Arbitrage Strategies")
    doc_tab_pcp, doc_tab_fb, doc_tab_irp = st.tabs([
        "Put-Call Parity", "Futures Basis", "Interest Rate Parity"])

    with doc_tab_pcp:
        st.markdown("""
#### Fundamental Relationship
The price of a European call minus a European put equals the difference between
the spot price and the present value of the strike:

$$C - P = S_0 - K \\cdot e^{-rT}$$

**Variables:**
- `C` = Call option market price
- `P` = Put option market price
- `S₀` = Current spot price of underlying
- `K` = Strike price (identical for both options)
- `r` = Continuously compounded risk-free rate
- `T` = Time to expiry in years

#### Arbitrage Strategies
| Gap | Condition | Strategy | Execution |
|-----|-----------|----------|-----------|
| Gap > 0 | Spot > Synthetic | **Conversion** | Buy Spot · Buy Put · Sell Call |
| Gap < 0 | Synthetic > Spot | **Reversal** | Short Spot · Sell Put · Buy Call |
| Gap ≈ 0 | Efficient market | **No Trade** | Wait and monitor |

#### Why is the payoff locked?
The three legs together form a synthetic forward position.
At any expiry price, the individual leg gains and losses cancel perfectly,
leaving only the arbitrage spread as profit.
        """)

    with doc_tab_fb:
        st.markdown("""
#### Cost-of-Carry Model
The fair (no-arbitrage) futures price is:

$$F^* = S \\cdot e^{(r + d) \\times T}$$

where `d` = holding cost or dividend yield (negative for dividends).

#### Strategies
- **Cash & Carry (F_mkt > F*):** Buy spot, sell futures, hold to expiry, deliver
- **Reverse C&C (F_mkt < F*):** Short spot, buy futures, accept delivery at expiry

#### Basis
`Basis = F_mkt − F*`

The basis decays to zero at expiry — this convergence guarantees the locked profit.
        """)

    with doc_tab_irp:
        st.markdown("""
#### Covered Interest Rate Parity
The theoretical forward exchange rate must satisfy:

$$F = S \\times e^{(r_d - r_f) \\times T}$$

where `r_d` = domestic rate (India), `r_f` = foreign rate (US), `S` = spot USD/INR.

#### Arbitrage
If `F_mkt ≠ F_theoretical`:
1. Borrow in the lower-rate currency
2. Convert at spot
3. Invest at the higher-rate currency
4. Lock in the forward to eliminate FX risk
5. Collect the rate differential as risk-free profit
        """)

    st.markdown("---")
    st.markdown("## 💸 Transaction Cost Model")
    cost_table_data = {
        "Cost Component":   ["Brokerage (flat)",   "STT on Spot",          "STT on Options (sell)", "STT on Futures"],
        "Rate":             ["₹20 per order",       "0.1% of trade value",  "0.0625% of premium",    "0.0125% of trade"],
        "Applied to":       ["All 4 orders",        "Spot buy side",        "Option sell side",      "Futures sell side"],
        "Typical (1 lot)":  ["₹80",                 "~₹1,300–₹1,700",      "~₹35–₹80",             "~₹30–₹50"],
    }
    st.dataframe(pd.DataFrame(cost_table_data), hide_index=True, use_container_width=True)

    st.markdown("---")
    st.markdown("## ⚠️ Disclaimer")
    st.warning("""
    This dashboard is developed for **educational and research purposes** as part of the
    Financial Engineering course at IIT Roorkee. It is **not financial advice**.

    - Arbitrage windows in real markets last milliseconds and are exploited by HFT algorithms
    - Transaction costs shown are approximate and may vary by broker and trade size
    - NSE option chain data requires manual entry due to API restrictions on cloud servers
    - All calculations assume European-style options and no early exercise
    - Past arbitrage patterns do not guarantee future opportunities

    Always consult a licensed financial advisor before executing real trades.
    """)

# ── GLOBAL FOOTER ─────────────────────────────────────────────────────────────
st.divider()
st.caption("⚠️ For educational and research purposes only. Not financial advice. "
           "Arbitrage windows are fleeting in real markets. | IIT Roorkee · Dept. of Management Studies · Financial Engineering")
