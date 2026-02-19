import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import urllib.request
import json
import datetime
try:
    from scipy.stats import norm as _norm
    SCIPY_OK = True
except ImportError:
    SCIPY_OK = False

st.set_page_config(page_title="Cross-Asset Arbitrage Monitor", layout="wide", page_icon="🏛️")

st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    label[data-testid="stWidgetLabel"] p { font-weight: bold !important; font-size: 14px !important; }
    div[data-testid="stMetricLabel"] p  { font-weight: bold !important; font-size: 13px !important; color: #333 !important; }
    div[data-testid="stMetricValue"]    { font-size: 24px; color: #1f77b4; font-weight: bold; }
    div[data-testid="stMetric"]         { background: #ffffff; border-radius: 10px; padding: 12px 16px;
                                          border: 1px solid #dee2e6; }
    .stTabs [data-baseweb="tab-list"]   { background-color: #e9ecef; border-radius: 8px; padding: 4px; }
    .stTabs [data-baseweb="tab"]        { border-radius: 6px; font-weight: 600; color: #495057; }
    .stTabs [aria-selected="true"]      { background-color: #1f77b4 !important; color: white !important; }
    .warning-box {
        background-color: #fff3cd; border-left: 5px solid #ffc107;
        padding: 10px 16px; border-radius: 6px; color: #856404;
        font-weight: 500; margin-top: 8px;
    }
    .nse-link-box {
        background-color: #e8f4fd; border-left: 5px solid #1f77b4;
        padding: 10px 16px; border-radius: 6px; color: #1a3a5c;
        font-size: 14px; margin-top: 6px;
    }
    .nse-link-box a { color: #1f77b4 !important; }
    .strategy-card {
        background-color: #ffffff; border-left: 5px solid #1f77b4;
        padding: 12px 16px; border-radius: 8px; margin-bottom: 10px;
        box-shadow: 0 1px 4px rgba(0,0,0,0.08);
    }
    .opp-card-green {
        background: linear-gradient(135deg, #d4edda, #c3e6cb);
        border-left: 6px solid #28a745; border-radius: 10px;
        padding: 14px 18px; margin-bottom: 10px;
    }
    .opp-card-red {
        background: linear-gradient(135deg, #f8d7da, #f5c6cb);
        border-left: 6px solid #dc3545; border-radius: 10px;
        padding: 14px 18px; margin-bottom: 10px;
    }
    .opp-card-grey {
        background: #f1f3f5; border-left: 6px solid #adb5bd; border-radius: 10px;
        padding: 14px 18px; margin-bottom: 10px;
    }
    .scanner-badge {
        display:inline-block; padding:3px 10px; border-radius:12px;
        font-size:12px; font-weight:700; margin-right:6px;
    }
    @keyframes pulse-green {
        0%,100% { box-shadow: 0 0 0 0 rgba(40,167,69,0.4); }
        50%      { box-shadow: 0 0 0 8px rgba(40,167,69,0); }
    }
    @keyframes pulse-red {
        0%,100% { box-shadow: 0 0 0 0 rgba(220,53,69,0.4); }
        50%      { box-shadow: 0 0 0 8px rgba(220,53,69,0); }
    }
    .signal-pulse-green { animation: pulse-green 2s infinite; }
    .signal-pulse-red   { animation: pulse-red   2s infinite; }
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
        "iv_pct":           20.0,
        "r_rate_pct":       6.75,
        "arb_threshold_pct":0.05,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_settings()

st.markdown("""
<div style="display:flex; align-items:center; gap:16px; margin-bottom:4px;">
  <span style="font-size:2rem;">🏛️</span>
  <div>
    <h1 style="margin:0; font-size:1.8rem; font-weight:900; color:#1f77b4;
               letter-spacing:-0.02em;">Cross-Asset Arbitrage Opportunity Monitor</h1>
    <p style="margin:0; font-size:13px; color:#6c757d;">
      IIT Roorkee &nbsp;·&nbsp; Department of Management Studies &nbsp;·&nbsp;
      Financial Engineering Project &nbsp;·&nbsp; Developed by: <b style="color:#495057;">Group 4</b>
    </p>
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
ticker_html = '''<div style="background:linear-gradient(90deg,#1f77b4,#2c95d6);
    border-radius:10px; padding:10px 20px;
    margin-bottom:16px; display:flex; gap:0; flex-wrap:wrap; align-items:center;">
    <span style="font-size:11px;color:#ffffff;font-weight:800;
          margin-right:20px;letter-spacing:0.1em;">● LIVE MARKET</span>'''

for asset_name, d in ticker_data.items():
    color  = "#22c55e" if d["chg"] >= 0 else "#ef4444"
    arrow  = "▲" if d["chg"] >= 0 else "▼"
    prefix = "₹" if asset_name != "USD/INR" else ""
    ticker_html += (
        '<span style="font-size:13px;font-weight:700;color:#ffffff;'
        'margin-right:24px;display:inline-flex;align-items:center;gap:5px;">'
        '<span style="color:#cce5ff;font-size:11px;font-weight:800;">{n}</span>'
        '{p}{v:,.2f}'
        '<span style="color:{c};font-size:11px;">{a} {p2}{chg:.2f} ({pct:.2f}%)</span>'
        '</span>'.format(
            n=asset_name, p=prefix, v=d["price"],
            c=color, a=arrow, p2=prefix, chg=abs(d["chg"]), pct=abs(d["chg_pct"]))
    )

ticker_html += '<span style="margin-left:auto;font-size:11px;color:#cce5ff;">Updated: {t}</span></div>'.format(t=now_str)
st.markdown(ticker_html, unsafe_allow_html=True)



# ── BSM GREEKS ENGINE ─────────────────────────────────────────────────────────
def _bsm_d1d2(S, K, r, T, sigma):
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return None, None
    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    return d1, d1 - sigma * np.sqrt(T)

def compute_greeks(S, K, r, T, sigma, option_type="call"):
    zero = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    if not SCIPY_OK: return zero
    d1, d2 = _bsm_d1d2(S, K, r, T, sigma)
    if d1 is None: return zero
    Nd1 = _norm.cdf(d1); Nd2 = _norm.cdf(d2); nd1 = _norm.pdf(d1)
    pv_k  = K * np.exp(-r * T)
    gamma = nd1 / (S * sigma * np.sqrt(T))
    vega  = S * np.sqrt(T) * nd1 / 100
    if option_type == "call":
        delta = Nd1
        theta = (-(S * nd1 * sigma) / (2 * np.sqrt(T)) - r * pv_k * Nd2) / 365
        rho   = pv_k * T * Nd2 / 100
    else:
        delta = Nd1 - 1
        theta = (-(S * nd1 * sigma) / (2 * np.sqrt(T)) + r * pv_k * _norm.cdf(-d2)) / 365
        rho   = -pv_k * T * _norm.cdf(-d2) / 100
    return {"delta": round(delta, 4), "gamma": round(gamma, 6),
            "theta": round(theta, 4), "vega": round(vega, 4), "rho": round(rho, 4)}

def combined_position_greeks(signal_type, call_g, put_g, total_units):
    if signal_type == "conversion":
        pd_ = (1.0 + put_g["delta"] - call_g["delta"]) * total_units
        pg  = (put_g["gamma"] - call_g["gamma"]) * total_units
        pt  = (put_g["theta"] - call_g["theta"]) * total_units
        pv  = (put_g["vega"]  - call_g["vega"])  * total_units
        pr  = (put_g["rho"]   - call_g["rho"])   * total_units
    elif signal_type == "reversal":
        pd_ = (-1.0 + call_g["delta"] - put_g["delta"]) * total_units
        pg  = (call_g["gamma"] - put_g["gamma"]) * total_units
        pt  = (call_g["theta"] - put_g["theta"]) * total_units
        pv  = (call_g["vega"]  - put_g["vega"])  * total_units
        pr  = (call_g["rho"]   - put_g["rho"])   * total_units
    else:
        pd_ = pg = pt = pv = pr = 0.0
    return {"delta": round(pd_, 4), "gamma": round(pg, 6),
            "theta": round(pt, 4), "vega": round(pv, 4), "rho": round(pr, 4)}

def greek_icon(val, thr):
    if abs(val) < thr:      return "🟢"
    elif abs(val) < thr*5:  return "🟡"
    else:                   return "🔴"

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
    st.subheader("🔬 Greeks (BSM)")
    iv_pct      = st.slider("Implied Volatility (%)", 5.0, 100.0,
                            float(st.session_state.iv_pct), step=0.5, key="sb_iv")
    st.session_state.iv_pct = iv_pct
    implied_vol = iv_pct / 100.0

    st.divider()
    if st.session_state.auto_refresh:
        st.success("🔄 Auto-refresh ON ({} s)".format(st.session_state.refresh_interval))
    else:
        st.info("🔄 Auto-refresh OFF")

# ══════════════════════════════════════════════════════════════════════════════
# TABS
# ══════════════════════════════════════════════════════════════════════════════
tab0, tab1, tab2, tab3, tab4, tab5, tab6 = st.tabs([
    "🔍 All Opportunities",
    "📐 Put-Call Parity",
    "🌍 Interest Rate Parity",
    "📦 Futures Basis (Cash & Carry)",
    "⚖️ Cross-Market Spread",
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
        banner_col = "#28a745"
        banner_txt = "✅ Found {} Profitable Arbitrage {} Across {} Assets".format(
            profitable_found,
            "Opportunity" if profitable_found == 1 else "Opportunities",
            len(scan_assets))
    else:
        banner_col = "#6c757d"
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
            sc = strategy_colors.get(opp["strategy"], "#6c757d")

            st.markdown(
                '<div class="{cls}">'
                '<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap;">'
                '<div>'
                '  <span class="scanner-badge" style="background:{sc};color:white;">#{n} {strat}</span>'
                '  <span class="scanner-badge" style="background:#495057;color:white;">{asset}</span>'
                '  {badge}'
                '</div>'
                '<div style="font-size:22px; font-weight:700; color:{pnl_col};">Net ₹{pnl:,.2f}</div>'
                '</div>'
                '<div style="margin-top:8px; display:flex; gap:24px; flex-wrap:wrap; font-size:13px;">'
                '  <span>📊 <b>Type:</b> {typ}</span>'
                '  <span>💹 <b>Spot:</b> {spot_label} {spot_val}</span>'
                '  <span>📈 <b>Gap:</b> {gap:.4f}</span>'
                '  <span>💰 <b>Gross:</b> ₹{gross:,.2f}</span>'
                '  <span>🧾 <b>Friction:</b> ₹{fric:,.2f}</span>'
                '  <span>📅 <b>Expiry:</b> {exp} ({days}d)</span>'
                '  <span>🚀 <b>Ann. Return:</b> {ann:.2f}%</span>'
                '  <span>📡 <b>Data:</b> {src}</span>'
                '</div>'
                '<div style="margin-top:6px; font-size:13px; color:#495057;">'
                '  ▶ <b>Execution:</b> {action}'
                '</div>'
                '</div>'.format(
                    cls=card_class, sc=sc, n=i+1,
                    strat=opp["strategy"], asset=opp["asset"], badge=profit_badge,
                    pnl_col="#155724" if opp["profitable"] else "#495057",
                    pnl=opp["net_pnl"],
                    typ=opp["type"],
                    spot_label="₹" if opp["asset"] != "USD/INR" else "",
                    spot_val="{:,.2f}".format(opp["spot"]),
                    gap=opp["gap"],
                    gross=opp["gross"], fric=opp["friction"],
                    exp=opp["expiry"].strftime("%d %b %Y"), days=opp["days"],
                    ann=opp["ann_return"], src=opp["data_src"],
                    action=opp["action"]),
                unsafe_allow_html=True)

        # ── Comparison bar chart ───────────────────────────────────────────
        if len(opportunities) > 1:
            st.markdown("### 📊 Opportunity Comparison")
            labels    = ["{} {}".format(o["asset"], o["strategy"][:3]) for o in opportunities]
            net_vals  = [o["net_pnl"] for o in opportunities]
            ann_vals  = [o["ann_return"] for o in opportunities]
            colors    = ["#28a745" if o["profitable"] else "#adb5bd" for o in opportunities]

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
                yaxis=dict(title=dict(text="Net P&L (₹)", font=dict(color="#28a745")),
                           tickformat=",.0f"),
                yaxis2=dict(title=dict(text="Ann. Return (%)", font=dict(color="#f59e0b")),
                            overlaying="y", side="right", tickformat=".1f"),
                height=380, margin=dict(t=45, b=40, l=10, r=10),
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                plot_bgcolor="#f8f9fa", paper_bgcolor="white", barmode="group")
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
            - **Interest Rate Parity**: Uses live USD/INR spot from yfinance, India 6.75% vs US 5.25%, 90-day tenor
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
            "✅ CONVERSION ARBITRAGE DETECTED", "#28a745", "Buy Spot  ·  Buy Put  ·  Sell Call", "conversion"
        net_pnl = gross_spread - total_friction
    elif spread_per_unit < -arb_threshold:
        signal_line, signal_color, strategy_desc, signal_type = \
            "🔴 REVERSAL ARBITRAGE DETECTED", "#dc3545", "Short Spot  ·  Sell Put  ·  Buy Call", "reversal"
        net_pnl = gross_spread - total_friction
    else:
        signal_line, signal_color, strategy_desc, signal_type = \
            "⚪ MARKET IS EFFICIENT — No Arbitrage", "#6c757d", "No Action", "none"
        net_pnl = -total_friction

    pnl_profitable = net_pnl > 0

    # ── METRICS ROW ───────────────────────────────────────────────────────────
    st.markdown("---")
    ann_return_pcp = (net_pnl / max(s0 * total_units * margin_pct, 1)) * (365 / max(days_to_expiry, 1)) * 100

    m1, m2, m3, m4, m5, m6, m7 = st.columns(7)
    m1.metric("Market Spot",       "₹{:,.2f}".format(s0))
    m2.metric("Synthetic Price",   "₹{:,.2f}".format(synthetic_spot))
    m3.metric("PV(Strike)",        "₹{:,.2f}".format(pv_k))
    m4.metric("Gap / unit",        "₹{:.2f}".format(abs(spread_per_unit)))
    m5.metric("Total Friction",    "₹{:,.2f}".format(total_friction))
    m6.metric("Net P&L",           "₹{:,.2f}".format(net_pnl),
              delta="✅ Profitable" if pnl_profitable else "❌ Loss after costs",
              delta_color="normal" if pnl_profitable else "inverse")
    m7.metric("Ann. Return",       "{:.2f}%".format(ann_return_pcp),
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
        # ── FEATURE 10: EXECUTION TIMELINE ───────────────────────────────────
        if signal_type != "none":
            st.markdown("**⏱️ Trade Execution Timeline:**")
            mid_day = max(days_to_expiry // 2, 1)
            tl_x = [0, mid_day, days_to_expiry]
            tl_labels = ["Day 0\nOpen Position", "Day {}\nMonitor".format(mid_day),
                         "Day {}\nClose / Expiry".format(days_to_expiry)]
            tl_y = [1, 1, 1]
            fig_tl = go.Figure()
            fig_tl.add_trace(go.Scatter(
                x=tl_x, y=tl_y, mode="lines+markers+text",
                line=dict(color="#f59e0b", width=3),
                marker=dict(size=[16,10,16],
                            color=["#22c55e","#f59e0b","#3b82f6"],
                            symbol=["circle","circle","star"],
                            line=dict(color="#112240", width=2)),
                text=tl_labels, textposition="bottom center",
                textfont=dict(size=10, color="#e2e8f0")))
            # Profit annotation at end
            fig_tl.add_annotation(
                x=days_to_expiry, y=1.15,
                text="<b>Net ₹{:,.0f}</b>".format(net_pnl),
                font=dict(size=13, color="#22c55e" if pnl_profitable else "#ef4444"),
                showarrow=False, bgcolor="#0d1b3e",
                bordercolor="#22c55e" if pnl_profitable else "#ef4444",
                borderwidth=1, borderpad=4)
            fig_tl.update_layout(
                height=150, margin=dict(t=20,b=50,l=20,r=20),
                xaxis=dict(title="Days", range=[-2, days_to_expiry+5],
                           showgrid=False, color="#94a3b8"),
                yaxis=dict(visible=False, range=[0.5, 1.5]),
                plot_bgcolor="#f8f9fa", paper_bgcolor="white",
                font=dict(color="#333333"), showlegend=False)
            st.plotly_chart(fig_tl, use_container_width=True)



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
            xaxis=dict(title="Spot Price at Expiry (₹)", tickformat=",.0f", showgrid=True, gridcolor="#e9ecef"),
            yaxis=dict(title=dict(text="Leg P&L (₹)", font=dict(color="#555")),
                       tickformat=",.0f", showgrid=False),
            yaxis2=dict(title=dict(text="Net P&L (₹)", font=dict(color=signal_color)),
                        tickformat=",.0f", overlaying="y", side="right",
                        range=[-net_pad, net_pad], showgrid=True, gridcolor="#e9ecef"),
            height=370, margin=dict(t=45, b=40, l=10, r=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            hovermode="x unified", plot_bgcolor="#f8f9fa", paper_bgcolor="white")
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
    # ── FEATURE 3: HISTORICAL GAP CHART ─────────────────────────────────────
    st.divider()
    with st.expander("📈 Historical Arbitrage Gap Analysis (last 30 days)", expanded=False):
        @st.cache_data(ttl=3600, show_spinner=False)
        def get_hist_gap(asset_n, k, r, t_days):
            try:
                ticker_h = TICKER_MAP[asset_n]
                hist = yf.Ticker(ticker_h).history(period="35d")["Close"].dropna()
                if len(hist) < 5:
                    return pd.DataFrame()
                dates, gaps, synths = [], [], []
                for i, (date, spot_h) in enumerate(hist.items()):
                    days_left = max(t_days - i, 1)
                    T_h       = days_left / 365.0
                    pv_k_h    = k * np.exp(-r * T_h)
                    # Use fixed option prices as proxy (ATM approx from BSM 20% vol)
                    import math
                    sigma_h = 0.20
                    if T_h > 0:
                        d1h = (math.log(spot_h/k) + (r + 0.5*sigma_h**2)*T_h) / (sigma_h*math.sqrt(T_h))
                        d2h = d1h - sigma_h*math.sqrt(T_h)
                        try:
                            from scipy.stats import norm as _n
                            c_h = spot_h*_n.cdf(d1h) - k*math.exp(-r*T_h)*_n.cdf(d2h)
                            p_h = k*math.exp(-r*T_h)*_n.cdf(-d2h) - spot_h*_n.cdf(-d1h)
                        except Exception:
                            c_h = spot_h * 0.025; p_h = spot_h * 0.018
                    else:
                        c_h = max(spot_h - k, 0); p_h = max(k - spot_h, 0)
                    synth_h = c_h - p_h + pv_k_h
                    gap_h   = spot_h - synth_h
                    dates.append(date); gaps.append(gap_h); synths.append(synth_h)
                df_hist = pd.DataFrame({"Date": dates, "Spot": hist.values[:len(dates)],
                                        "Synthetic": synths, "Gap": gaps})
                return df_hist
            except Exception:
                return pd.DataFrame()

        df_gap = get_hist_gap(asset, strike, r_rate, days_to_expiry)
        if df_gap.empty:
            st.info("Historical data unavailable. Live spot required.")
        else:
            fig_hist = go.Figure()
            colors_gap = ["#22c55e" if g > 0 else "#ef4444" for g in df_gap["Gap"]]
            fig_hist.add_trace(go.Bar(
                x=df_gap["Date"], y=df_gap["Gap"],
                name="Arbitrage Gap (Spot − Synthetic)",
                marker_color=colors_gap, opacity=0.8))
            fig_hist.add_hline(y=0, line_dash="dash", line_color="#94a3b8", line_width=1)
            fig_hist.add_hline(y=s0 * (arb_threshold_pct/100),
                               line_dash="dot", line_color="#f59e0b", line_width=1.5,
                               annotation_text="Long threshold", annotation_font_color="#f59e0b")
            fig_hist.add_hline(y=-s0 * (arb_threshold_pct/100),
                               line_dash="dot", line_color="#f59e0b", line_width=1.5,
                               annotation_text="Short threshold", annotation_font_color="#f59e0b")
            fig_hist.update_layout(
                title="30-Day Historical PCP Gap — {} (BSM-estimated options)".format(asset),
                xaxis=dict(title="Date", showgrid=False),
                yaxis=dict(title="Gap per unit (₹)", tickformat=",.2f",
                           gridcolor="#e9ecef"),
                height=300, margin=dict(t=40,b=30,l=10,r=10),
                plot_bgcolor="#f8f9fa", paper_bgcolor="white",
                font=dict(color="#333333"), showlegend=False)
            st.plotly_chart(fig_hist, use_container_width=True)

            avg_gap = df_gap["Gap"].mean()
            pos_days = (df_gap["Gap"] > s0*(arb_threshold_pct/100)).sum()
            neg_days = (df_gap["Gap"] < -s0*(arb_threshold_pct/100)).sum()
            hg1, hg2, hg3, hg4 = st.columns(4)
            hg1.metric("Avg Gap (30d)",       "₹{:.2f}".format(avg_gap))
            hg2.metric("Conversion Days",     "{}/{}".format(pos_days, len(df_gap)))
            hg3.metric("Reversal Days",       "{}/{}".format(neg_days, len(df_gap)))
            hg4.metric("Today's Gap",         "₹{:.2f}".format(spread_per_unit))
            st.caption("⚠️ Historical gaps computed using BSM-estimated theoretical option prices at 20% implied vol. "
                       "Actual market gaps would differ based on real option premiums.")



    # ── GREEKS PANEL ──────────────────────────────────────────────────────────
    st.divider()
    with st.expander("🔬 Option Greeks Analysis (Black-Scholes-Merton)", expanded=False):
        if not SCIPY_OK:
            st.warning("Add `scipy>=1.11.0` to requirements.txt to enable Greeks.")
        else:
            call_g = compute_greeks(s0, strike, r_rate, t, implied_vol, "call")
            put_g  = compute_greeks(s0, strike, r_rate, t, implied_vol, "put")
            comb_g = combined_position_greeks(signal_type, call_g, put_g, total_units)

            st.caption("S₀=₹{:,.2f} | K=₹{:,.0f} | σ={:.1f}% | T={} days ({:.4f}y) | r={:.2f}%".format(
                s0, strike, implied_vol*100, days_to_expiry, t, r_rate*100))

            gdf = pd.DataFrame({
                "Position": ["📞 Call (per unit)", "📋 Put (per unit)", "⚡ Combined (total)"],
                "Delta Δ":  ["{} {:.4f}".format(greek_icon(call_g["delta"],0.05), call_g["delta"]),
                             "{} {:.4f}".format(greek_icon(put_g["delta"],0.05),  put_g["delta"]),
                             "{} {:.4f}".format(greek_icon(comb_g["delta"],0.05*total_units), comb_g["delta"])],
                "Gamma Γ":  ["{} {:.6f}".format(greek_icon(call_g["gamma"],0.001), call_g["gamma"]),
                             "{} {:.6f}".format(greek_icon(put_g["gamma"],0.001),  put_g["gamma"]),
                             "{} {:.6f}".format(greek_icon(comb_g["gamma"],0.001), comb_g["gamma"])],
                "Theta Θ/day": ["{} {:.4f}".format(greek_icon(call_g["theta"],5), call_g["theta"]),
                                "{} {:.4f}".format(greek_icon(put_g["theta"],5),  put_g["theta"]),
                                "{} {:.4f}".format(greek_icon(comb_g["theta"],5), comb_g["theta"])],
                "Vega ν/1%vol": ["{} {:.4f}".format(greek_icon(call_g["vega"],10), call_g["vega"]),
                                 "{} {:.4f}".format(greek_icon(put_g["vega"],10),  put_g["vega"]),
                                 "{} {:.4f}".format(greek_icon(comb_g["vega"],10), comb_g["vega"])],
                "Rho ρ/1%rate": ["{} {:.4f}".format(greek_icon(call_g["rho"],5), call_g["rho"]),
                                 "{} {:.4f}".format(greek_icon(put_g["rho"],5),  put_g["rho"]),
                                 "{} {:.4f}".format(greek_icon(comb_g["rho"],5), comb_g["rho"])],
            })
            st.dataframe(gdf, hide_index=True, use_container_width=True)

            gi1, gi2 = st.columns(2)
            with gi1:
                if abs(comb_g["delta"]) < 0.05 * total_units:
                    st.success("✅ Delta ≈ 0 — Position is delta-neutral.")
                else:
                    st.warning("⚠️ Delta = {:.2f} — Consider hedging {:.0f} spot units.".format(
                        comb_g["delta"], -comb_g["delta"]))
                if abs(comb_g["vega"]) < 10:
                    st.success("✅ Vega ≈ 0 — Vega-neutral. IV changes won't affect P&L.")
                else:
                    st.warning("⚠️ Vega = {:.2f} — 1% IV move changes P&L by ₹{:.2f}.".format(
                        comb_g["vega"], comb_g["vega"]))
            with gi2:
                st.info("📅 Theta = {:.4f} → Position {s} ₹{:.2f}/day from time decay.".format(
                    comb_g["theta"], abs(comb_g["theta"]),
                    s="earns" if comb_g["theta"] > 0 else "loses"))
                st.info("📈 Rho = {:.4f} → 1% rate rise changes P&L by ₹{:.2f}.".format(
                    comb_g["rho"], comb_g["rho"]))

            gvals = [abs(comb_g["delta"]), abs(comb_g["gamma"])*1000,
                     abs(comb_g["theta"]), abs(comb_g["vega"]), abs(comb_g["rho"])]
            fg = go.Figure(go.Bar(
                x=["Delta", "Gamma×1000", "Theta", "Vega", "Rho"], y=gvals,
                marker_color=["#28a745" if v<0.1 else "#ffc107" if v<0.5 else "#dc3545" for v in gvals],
                text=["{:.5f}".format(v) for v in gvals], textposition="outside"))
            fg.update_layout(title="Combined Position Greeks (🟢=hedged 🟡=moderate 🔴=exposed)",
                             yaxis=dict(title="Absolute Value"), height=280,
                             margin=dict(t=40,b=20,l=10,r=10),
                             plot_bgcolor="#f8f9fa", paper_bgcolor="white", showlegend=False)
            st.plotly_chart(fg, use_container_width=True)
            st.info("A perfect PCP arbitrage has Delta≈0, Gamma≈0, Vega≈0. Residual Theta and Rho "
                    "confirm the position is locked but sensitive to time decay and rate changes.")
    # ── FEATURE 8: SENSITIVITY ANALYSIS ─────────────────────────────────────
    st.divider()
    with st.expander("🎯 Sensitivity Analysis — How P&L Changes with Rate & Volatility", expanded=False):
        sa1, sa2 = st.columns(2)
        with sa1:
            st.markdown("##### Net P&L vs Risk-Free Rate")
            r_range   = np.linspace(0.04, 0.10, 25)
            pnl_r     = []
            for r_test in r_range:
                pv_k_t   = strike * np.exp(-r_test * t)
                synth_t  = c_mkt - p_mkt + pv_k_t
                gap_t    = s0 - synth_t
                gross_t  = abs(gap_t) * total_units
                net_t    = gross_t - total_friction
                pnl_r.append(net_t)
            fig_sa1 = go.Figure()
            fig_sa1.add_trace(go.Scatter(
                x=r_range * 100, y=pnl_r, mode="lines+markers",
                line=dict(color="#f59e0b", width=2.5),
                marker=dict(size=5, color="#f59e0b"),
                fill="tozeroy", fillcolor="rgba(245,158,11,0.12)"))
            fig_sa1.add_vline(x=r_rate*100, line_dash="dash", line_color="#22c55e",
                              annotation_text="Current {:.2f}%".format(r_rate*100),
                              annotation_font_color="#22c55e")
            fig_sa1.add_hline(y=0, line_dash="dash", line_color="#ef4444", line_width=1)
            fig_sa1.update_layout(
                xaxis=dict(title="Risk-Free Rate (%)", gridcolor="#e9ecef"),
                yaxis=dict(title="Net P&L (₹)", tickformat=",.0f", gridcolor="#e9ecef"),
                height=260, margin=dict(t=20,b=30,l=10,r=10),
                plot_bgcolor="#f8f9fa", paper_bgcolor="white",
                font=dict(color="#333333"), showlegend=False)
            st.plotly_chart(fig_sa1, use_container_width=True)

        with sa2:
            st.markdown("##### Net P&L vs Call–Put Spread (Option Price Sensitivity)")
            spread_range = np.linspace(-50, 50, 25)   # ₹ change in C−P spread
            pnl_cp = []
            for delta_cp in spread_range:
                c_test   = c_mkt + delta_cp / 2
                p_test   = p_mkt - delta_cp / 2
                synth_t  = c_test - p_test + pv_k
                gap_t    = s0 - synth_t
                gross_t  = abs(gap_t) * total_units
                fric_t   = brokerage * (fno_orders+2) + stt_spot + (c_test+p_test)*total_units*0.000625
                net_t    = gross_t - fric_t
                pnl_cp.append(net_t)
            fig_sa2 = go.Figure()
            fig_sa2.add_trace(go.Scatter(
                x=spread_range, y=pnl_cp, mode="lines+markers",
                line=dict(color="#3b82f6", width=2.5),
                marker=dict(size=5, color="#3b82f6"),
                fill="tozeroy", fillcolor="rgba(59,130,246,0.12)"))
            fig_sa2.add_vline(x=0, line_dash="dash", line_color="#22c55e",
                              annotation_text="Current", annotation_font_color="#22c55e")
            fig_sa2.add_hline(y=0, line_dash="dash", line_color="#ef4444", line_width=1)
            fig_sa2.update_layout(
                xaxis=dict(title="Change in (C − P) spread (₹)", gridcolor="#e9ecef"),
                yaxis=dict(title="Net P&L (₹)", tickformat=",.0f", gridcolor="#e9ecef"),
                height=260, margin=dict(t=20,b=30,l=10,r=10),
                plot_bgcolor="#f8f9fa", paper_bgcolor="white",
                font=dict(color="#333333"), showlegend=False)
            st.plotly_chart(fig_sa2, use_container_width=True)

        # Transaction cost breakdown pie chart
        st.markdown("##### 🥧 Transaction Cost Breakdown")
        pie_labels = ["Brokerage", "STT on Spot", "STT on Options"]
        pie_values = [total_brokerage, stt_spot, stt_options]
        fig_pie = go.Figure(go.Pie(
            labels=pie_labels, values=pie_values,
            hole=0.5,
            marker=dict(colors=["#f59e0b", "#3b82f6", "#8b5cf6"],
                        line=dict(color="#112240", width=2)),
            textinfo="label+percent",
            textfont=dict(color="#e2e8f0", size=13)))
        fig_pie.update_layout(
            height=260, margin=dict(t=20,b=10,l=10,r=10),
            plot_bgcolor="#f8f9fa", paper_bgcolor="white",
            font=dict(color="#333333"),
            annotations=[dict(text="₹{:,.0f}".format(total_friction),
                              x=0.5, y=0.5, font_size=16, font_color="#f59e0b",
                              showarrow=False)])
        st.plotly_chart(fig_pie, use_container_width=True)
        st.caption("Sensitivity analysis shows how robust your arbitrage is. "
                   "If Net P&L stays positive across a wide range of rate changes, "
                   "the opportunity is genuine and not rate-dependent.")



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
        irp_color  = "#dc3545"
    elif irp_gap < -irp_threshold:
        irp_signal = "✅ FORWARD TOO CHEAP — Borrow INR · Invest USD · Buy Forward"
        irp_color  = "#28a745"
    else:
        irp_signal = "⚪ IRP HOLDS — No Covered Arbitrage Opportunity"
        irp_color  = "#6c757d"

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
        plot_bgcolor="#f8f9fa", paper_bgcolor="white", showlegend=False)
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
        fb_color  = "#28a745"
        fb_strategy = "Cash & Carry"
    elif fb_basis < -fb_threshold:
        fb_signal = "🔴 REVERSE CASH & CARRY — Short Spot · Buy Futures · Accept Delivery"
        fb_color  = "#dc3545"
        fb_strategy = "Reverse Cash & Carry"
    else:
        fb_signal = "⚪ BASIS FAIR — No Futures Arbitrage Opportunity"
        fb_color  = "#6c757d"
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
                                name="Fair Futures F*", line=dict(color="#28a745", width=2)))
    fig_fb.add_trace(go.Scatter(x=[fb_days, 0], y=[fb_mkt, fb_mkt], mode="lines",
                                name="Market Futures (entry)", line=dict(color="#dc3545", width=2, dash="dash")))
    fig_fb.add_trace(go.Scatter(x=days_arr[::-1], y=basis_arr[::-1], mode="lines",
                                name="Basis (Fmkt − F*)", line=dict(color="#ff7f0e", width=1.5, dash="dot"),
                                yaxis="y2"))
    fig_fb.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1, yref="y2")
    fig_fb.update_layout(
        title="Basis Decay: Fair Futures Converges to Market Price at Expiry",
        xaxis=dict(title="Days Remaining to Expiry", autorange="reversed"),
        yaxis=dict(title=dict(text="Price (₹)", font=dict(color="#28a745")), tickformat=",.2f"),
        yaxis2=dict(title=dict(text="Basis (₹)", font=dict(color="#ff7f0e")),
                    overlaying="y", side="right", tickformat=",.2f"),
        height=320, margin=dict(t=40,b=30,l=10,r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor="#f8f9fa", paper_bgcolor="white")
    st.plotly_chart(fig_fb, use_container_width=True)
    st.caption("As time passes, F* rises (cost of carry accumulates) and converges to F_mkt at expiry. "
               "The basis (orange dotted) decays to zero — this convergence locks in the arbitrage profit.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 4 — CROSS-MARKET SPREAD ARBITRAGE
# ══════════════════════════════════════════════════════════════════════════════
with tab4:
    st.subheader("⚖️ Cross-Market Spread Arbitrage (Statistical)")
    st.markdown("""
    **Theory — Pairs Trading / Cross-Market Spread:**
    Two assets that share fundamental economic linkages (same sector, correlated indices, ADR vs domestic)
    tend to maintain a stable long-run price ratio (the **spread**). When the spread deviates significantly
    from its historical mean, a mean-reversion arbitrage can be executed:

    - **Spread = Price_A − β × Price_B**  (β = hedge ratio from historical regression)
    - **Z-Score = (Spread − Mean) / Std Dev**
    - **|Z-Score| > 2.0** → Statistically significant deviation → Trade signal
    """)

    with st.expander("📖 How Cross-Market Spread Arbitrage Works", expanded=False):
        st.markdown("""
        **When Z-Score > +2 (Spread too wide — Asset A overpriced vs B):**
        1. SHORT Asset A
        2. LONG Asset B (β units for every 1 unit of A)
        3. Hold until spread reverts to mean
        4. Profit = entry spread − exit spread (after costs)

        **When Z-Score < −2 (Spread too narrow — Asset A underpriced vs B):**
        1. LONG Asset A
        2. SHORT Asset B (β units for every 1 unit of A)
        3. Hold until spread reverts to mean
        4. Profit = exit spread − entry spread (after costs)

        **Statistical basis:** Based on historical price correlation over a lookback window.
        This is not a risk-free arbitrage but a **statistical arbitrage** — the spread may widen
        further before reverting. Used by hedge funds and quant desks.
        """)

    cms_c1, cms_c2 = st.columns(2)
    with cms_c1:
        asset_a = st.selectbox("Asset A (Long/Short leg)", list(LOT_SIZES.keys()), index=0, key="cms_a")
        lots_a  = st.number_input("Lots (Asset A)", min_value=1, value=1, step=1, key="cms_lots_a")
    with cms_c2:
        asset_b = st.selectbox("Asset B (Hedge leg)", list(LOT_SIZES.keys()), index=1, key="cms_b")
        lots_b  = st.number_input("Lots (Asset B)", min_value=1, value=1, step=1, key="cms_lots_b")

    lookback = st.slider("Lookback Period (days)", 20, 252, 60, step=5, key="cms_lookback",
                         help="Historical window for computing spread mean and std dev")
    z_entry  = st.slider("Z-Score Entry Threshold", 1.0, 3.0, 2.0, step=0.1, key="cms_z",
                         help="Trade when |Z-Score| exceeds this value")

    # Fetch historical prices
    @st.cache_data(ttl=300, show_spinner=False)
    def fetch_hist(ticker_a, ticker_b, days):
        try:
            period = "{}d".format(min(days + 30, 365))
            da = yf.Ticker(ticker_a).history(period=period)["Close"].tail(days)
            db = yf.Ticker(ticker_b).history(period=period)["Close"].tail(days)
            df = pd.DataFrame({"A": da.values, "B": db.values},
                              index=da.index[:min(len(da), len(db))])
            return df.dropna()
        except Exception:
            return pd.DataFrame()

    with st.spinner("Fetching historical prices for {} & {}...".format(asset_a, asset_b)):
        hist_df = fetch_hist(TICKER_MAP[asset_a], TICKER_MAP[asset_b], lookback + 30)

    if hist_df.empty or len(hist_df) < 10:
        st.warning("Could not fetch sufficient historical data. Using fallback spot prices for illustration.")
        sp_a = FALLBACK_SPOTS[asset_a]
        sp_b = FALLBACK_SPOTS[asset_b]
        beta = 1.0
        spread_mean = 0.0
        spread_std  = sp_a * 0.02
        spread_now  = sp_a - beta * sp_b
        z_score     = 0.0
        hist_available = False
    else:
        hist_df = hist_df.tail(lookback)
        sp_a    = float(hist_df["A"].iloc[-1])
        sp_b    = float(hist_df["B"].iloc[-1])
        # Hedge ratio β via OLS
        beta    = float(np.polyfit(hist_df["B"], hist_df["A"], 1)[0])
        spread_series = hist_df["A"] - beta * hist_df["B"]
        spread_mean   = float(spread_series.mean())
        spread_std    = float(spread_series.std())
        spread_now    = float(spread_series.iloc[-1])
        z_score       = (spread_now - spread_mean) / spread_std if spread_std > 0 else 0.0
        hist_available = True

    units_a = lots_a * LOT_SIZES[asset_a]
    units_b = lots_b * LOT_SIZES[asset_b]
    entry_spread   = abs(spread_now - spread_mean)
    cms_gross      = entry_spread * min(units_a, units_b)
    cms_friction   = brokerage * 4   # 2 open + 2 close orders
    cms_net        = cms_gross - cms_friction
    cms_profitable = cms_net > 0

    cms_threshold = spread_std * z_entry
    if z_score > z_entry:
        cms_signal  = "🔴 SPREAD WIDE — Short {} · Long {}".format(asset_a, asset_b)
        cms_color   = "#dc3545"
        cms_action  = "Short A, Long B"
    elif z_score < -z_entry:
        cms_signal  = "✅ SPREAD NARROW — Long {} · Short {}".format(asset_a, asset_b)
        cms_color   = "#28a745"
        cms_action  = "Long A, Short B"
    else:
        cms_signal  = "⚪ SPREAD WITHIN BOUNDS — No Statistical Arbitrage"
        cms_color   = "#6c757d"
        cms_action  = "Wait"

    st.markdown("---")
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("{} Price".format(asset_a), "₹{:,.2f}".format(sp_a))
    s2.metric("{} Price".format(asset_b), "₹{:,.2f}".format(sp_b))
    s3.metric("Hedge Ratio β",  "{:.4f}".format(beta))
    s4.metric("Spread Z-Score", "{:.3f}".format(z_score),
              delta="Entry @ ±{:.1f}".format(z_entry), delta_color="off")
    s5.metric("Net P&L (est.)", "₹{:,.2f}".format(cms_net),
              delta="Spread reverts to mean" if cms_profitable else "Spread too small", delta_color="off")

    st.markdown(
        '<div style="background:{c}; padding:14px; border-radius:10px; text-align:center; color:white; margin:12px 0;">'
        '<h2 style="margin:0; font-size:20px;">{s}</h2>'
        '<p style="margin:4px 0 0; font-size:14px; opacity:.9;">Z-Score={z:.3f} | Threshold=±{t:.1f} | Action: {a}</p>'
        '</div>'.format(c=cms_color, s=cms_signal, z=z_score, t=z_entry, a=cms_action),
        unsafe_allow_html=True)

    cms_detail = pd.DataFrame({
        "Metric": ["Current {} Price".format(asset_a), "Current {} Price".format(asset_b),
                   "Hedge Ratio β (OLS, {} days)".format(lookback),
                   "Current Spread = A − β·B",
                   "Historical Mean Spread",
                   "Historical Std Dev",
                   "Z-Score = (Spread−Mean)/Std",
                   "Entry Threshold (±Z×Std)",
                   "Estimated Gross P&L (if reversion to mean)",
                   "Transaction Costs", "Estimated Net P&L"],
        "Value": [
            "₹{:,.2f}".format(sp_a), "₹{:,.2f}".format(sp_b),
            "{:.4f}".format(beta),
            "₹{:,.4f}".format(spread_now),
            "₹{:,.4f}".format(spread_mean),
            "₹{:,.4f}".format(spread_std),
            "{:.3f}{}".format(z_score, " ← SIGNAL!" if abs(z_score) > z_entry else ""),
            "±₹{:,.4f}".format(cms_threshold),
            "₹{:,.2f}".format(cms_gross),
            "₹{:,.2f}".format(cms_friction),
            "₹{:,.2f}".format(cms_net),
        ]
    })
    st.dataframe(cms_detail, hide_index=True, use_container_width=True)

    # Spread history chart
    if hist_available and len(hist_df) > 5:
        st.markdown("#### 📊 Historical Spread & Z-Score")
        spread_hist = hist_df["A"] - beta * hist_df["B"]
        z_hist      = (spread_hist - spread_mean) / spread_std

        fig_cms = go.Figure()
        fig_cms.add_trace(go.Scatter(
            x=list(range(len(spread_hist))), y=spread_hist.values,
            mode="lines", name="Spread (A − β·B)",
            line=dict(color="#1f77b4", width=2)))
        fig_cms.add_hline(y=spread_mean, line_dash="dash", line_color="green",
                          annotation_text="Mean {:.2f}".format(spread_mean))
        fig_cms.add_hline(y=spread_mean + z_entry*spread_std, line_dash="dot", line_color="#dc3545",
                          annotation_text="+{:.0f}σ".format(z_entry))
        fig_cms.add_hline(y=spread_mean - z_entry*spread_std, line_dash="dot", line_color="#dc3545",
                          annotation_text="-{:.0f}σ".format(z_entry))
        fig_cms.add_trace(go.Scatter(
            x=list(range(len(z_hist))), y=z_hist.values,
            mode="lines", name="Z-Score",
            line=dict(color="#ff7f0e", width=1.5, dash="dot"), yaxis="y2"))
        fig_cms.update_layout(
            title="Spread History — {} vs {} (last {} days)".format(asset_a, asset_b, lookback),
            xaxis=dict(title="Trading Days"),
            yaxis=dict(title=dict(text="Spread (₹)", font=dict(color="#1f77b4"))),
            yaxis2=dict(title=dict(text="Z-Score", font=dict(color="#ff7f0e")),
                        overlaying="y", side="right"),
            height=340, margin=dict(t=40,b=30,l=10,r=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            plot_bgcolor="#f8f9fa", paper_bgcolor="white")
        st.plotly_chart(fig_cms, use_container_width=True)
        st.caption("Red dotted lines = entry thresholds (±{:.0f}σ). Trade when spread crosses threshold and expect mean reversion. "
                   "⚠️ Statistical arbitrage carries model risk — spreads may not always revert.".format(z_entry))

    st.warning("⚠️ Statistical arbitrage is NOT risk-free. Unlike PCP or IRP, spread reversion is probabilistic. "
               "Use proper stop-losses and position sizing in practice.")

# ══════════════════════════════════════════════════════════════════════════════
# TAB 5 — SETTINGS & CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════
with tab5:
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
        new_iv_default    = st.slider("Default Implied Volatility (%)", 5.0, 80.0,
                                       float(st.session_state.iv_pct),
                                       step=0.5, key="cfg_iv")
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
            st.session_state.iv_pct            = new_iv_default
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
- Default IV: {iv:.1f}%
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
        iv=st.session_state.iv_pct,
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
with tab6:
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
    doc_tab_pcp, doc_tab_fb, doc_tab_irp, doc_tab_cms = st.tabs([
        "Put-Call Parity", "Futures Basis", "Interest Rate Parity", "Cross-Market Spread"])

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

    with doc_tab_cms:
        st.markdown("""
#### Statistical Spread Arbitrage
Two correlated assets maintain a long-run price relationship.
The spread is: `Spread = Price_A − β × Price_B`

where `β` = hedge ratio from OLS regression.

**Z-Score:** `Z = (Spread − Mean) / Std Dev`

When |Z| > threshold (typically 2.0):
- Z > +2: Short A, Long B (spread will narrow)
- Z < −2: Long A, Short B (spread will widen)

⚠️ **Note:** Unlike PCP and IRP, this is statistical arbitrage — not risk-free.
Use stop-losses and proper position sizing.
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
