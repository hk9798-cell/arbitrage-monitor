
import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import urllib.request
import json

st.set_page_config(page_title="Arbitrage Monitor", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    label[data-testid="stWidgetLabel"] p { font-weight: bold !important; font-size: 15px !important; }
    div[data-testid="stMetricLabel"] p { font-weight: bold !important; font-size: 14px !important; }
    div[data-testid="stMetricValue"] { font-size: 26px; color: #1f77b4; font-weight: bold; }
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
    </style>
""", unsafe_allow_html=True)

st.title("🏛️ Cross-Asset Arbitrage Opportunity Monitor")

LOT_SIZES      = {"NIFTY": 65,   "RELIANCE": 250, "TCS": 175, "SBIN": 1500, "INFY": 400}
STRIKE_STEP    = {"NIFTY": 50,   "RELIANCE": 20,  "TCS": 50,  "SBIN": 5,    "INFY": 20}
FALLBACK_SPOTS = {"NIFTY": 25800.0, "RELIANCE": 1420.0, "TCS": 3850.0, "SBIN": 810.0, "INFY": 1580.0}
TICKER_MAP     = {"NIFTY": "^NSEI", "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "SBIN": "SBIN.NS", "INFY": "INFY.NS"}

# NSE option chain URLs for manual lookup
NSE_CHAIN_URLS = {
    "NIFTY":    "https://www.nseindia.com/option-chain",
    "RELIANCE": "https://www.nseindia.com/get-quotes/derivatives?symbol=RELIANCE",
    "TCS":      "https://www.nseindia.com/get-quotes/derivatives?symbol=TCS",
    "SBIN":     "https://www.nseindia.com/get-quotes/derivatives?symbol=SBIN",
    "INFY":     "https://www.nseindia.com/get-quotes/derivatives?symbol=INFY",
}

with st.sidebar:
    st.header("⚙️ Parameters")
    asset = st.selectbox("Select Asset", list(LOT_SIZES.keys()))
    num_lots = st.number_input("Number of Lots", min_value=1, value=1, step=1)
    r_rate = st.slider("Risk-Free Rate (%)", 4.0, 10.0, 6.75, step=0.25) / 100
    days_to_expiry = st.number_input("Days to Expiry", value=15, min_value=1, max_value=365)
    st.divider()
    brokerage = st.number_input("Brokerage per Order (₹)", value=20.0, min_value=0.0, step=5.0,
                                help="Flat fee per order e.g. Zerodha ₹20")
    margin_pct = st.slider("Margin Requirement (%)", 10, 40, 20) / 100
    st.divider()
    arb_threshold_pct = st.slider("Arbitrage Threshold (%)", min_value=0.01, max_value=0.5,
                                  value=0.05, step=0.01,
                                  help="Minimum gap as % of spot. Filters bid-ask noise.")

# ── DATA ENGINE ───────────────────────────────────────────────────────────────
def _try_nse_api(asset_name):
    """Try multiple NSE API approaches."""
    is_index = (asset_name == "NIFTY")
    symbol = asset_name

    # Approach A: nsepython
    try:
        from nsepython import nse_optionchain_scrapper
        data = nse_optionchain_scrapper(symbol)
        spot   = float(data["records"]["underlyingValue"])
        expiry = data["records"]["expiryDates"][0]
        calls_rows, puts_rows = [], []
        for rec in data["records"]["data"]:
            if rec.get("expiryDate") != expiry:
                continue
            k = float(rec["strikePrice"])
            if "CE" in rec:
                ce = rec["CE"]
                calls_rows.append({"strike": k,
                                   "lastPrice": float(ce.get("lastPrice", 0) or 0),
                                   "openInterest": float(ce.get("openInterest", 0) or 0),
                                   "volume": float(ce.get("totalTradedVolume", 0) or 0)})
            if "PE" in rec:
                pe = rec["PE"]
                puts_rows.append({"strike": k,
                                  "lastPrice": float(pe.get("lastPrice", 0) or 0),
                                  "openInterest": float(pe.get("openInterest", 0) or 0),
                                  "volume": float(pe.get("totalTradedVolume", 0) or 0)})
        calls_df = pd.DataFrame(calls_rows)
        puts_df  = pd.DataFrame(puts_rows)
        if not calls_df.empty:
            return round(spot, 2), calls_df, puts_df, expiry
    except Exception:
        pass

    # Approach B: urllib with browser headers (sometimes bypasses NSE block)
    try:
        url = (
            "https://www.nseindia.com/api/option-chain-indices?symbol={}".format(symbol)
            if is_index else
            "https://www.nseindia.com/api/option-chain-equities?symbol={}".format(symbol)
        )
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://www.nseindia.com/",
        })
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode())
        spot   = float(data["records"]["underlyingValue"])
        expiry = data["records"]["expiryDates"][0]
        calls_rows, puts_rows = [], []
        for rec in data["records"]["data"]:
            if rec.get("expiryDate") != expiry:
                continue
            k = float(rec["strikePrice"])
            if "CE" in rec:
                ce = rec["CE"]
                calls_rows.append({"strike": k,
                                   "lastPrice": float(ce.get("lastPrice", 0) or 0),
                                   "openInterest": float(ce.get("openInterest", 0) or 0),
                                   "volume": float(ce.get("totalTradedVolume", 0) or 0)})
            if "PE" in rec:
                pe = rec["PE"]
                puts_rows.append({"strike": k,
                                  "lastPrice": float(pe.get("lastPrice", 0) or 0),
                                  "openInterest": float(pe.get("openInterest", 0) or 0),
                                  "volume": float(pe.get("totalTradedVolume", 0) or 0)})
        calls_df = pd.DataFrame(calls_rows)
        puts_df  = pd.DataFrame(puts_rows)
        if not calls_df.empty:
            return round(spot, 2), calls_df, puts_df, expiry
    except Exception:
        pass

    return None

@st.cache_data(ttl=90, show_spinner=False)
def get_market_data(asset_name):
    """
    Layer 1: NSE API (multiple approaches)
    Layer 2: yfinance — spot only for Indian assets (no option chain)
    Layer 3: Static fallback
    """
    # Layer 1: NSE API
    result = _try_nse_api(asset_name)
    if result:
        spot, calls_df, puts_df, expiry = result
        return spot, calls_df, puts_df, expiry, None, "nse"

    # Layer 2: yfinance for spot price only
    try:
        stock = yf.Ticker(TICKER_MAP[asset_name])
        hist  = stock.history(period="2d")
        if not hist.empty:
            spot = float(round(hist["Close"].iloc[-1], 2))
            return spot, pd.DataFrame(), pd.DataFrame(), None, \
                "NSE option chain unavailable from cloud server. Live spot ✅ | Enter Call & Put prices manually from NSE website.", "yf_spot"
    except Exception:
        pass

    # Layer 3: Static fallback
    return (FALLBACK_SPOTS[asset_name], pd.DataFrame(), pd.DataFrame(), None,
            "All live sources unavailable. Using fallback spot. Enter prices manually.", "fallback")

with st.spinner("📡 Fetching data for {}...".format(asset)):
    s0, calls_df, puts_df, expiry_date, fetch_error, data_source = get_market_data(asset)

# Status display
if data_source == "nse":
    st.success("✅ Live NSE option chain loaded — Expiry: **{}**  |  Spot: ₹{:,.2f}".format(expiry_date, s0))
elif data_source == "yf_spot":
    st.warning("⚠️ {}".format(fetch_error))
    # Show helpful NSE link so user can look up option prices
    st.markdown(
        '<div class="nse-link-box">📋 <strong>Get option prices from NSE:</strong> '
        '<a href="{url}" target="_blank">Open {asset} Option Chain on NSE ↗</a><br>'
        'Look up the ATM strike Call & Put last traded prices and enter them below.</div>'.format(
            url=NSE_CHAIN_URLS[asset], asset=asset),
        unsafe_allow_html=True
    )
else:
    st.error("⚠️ {}".format(fetch_error))
    st.markdown(
        '<div class="nse-link-box">📋 <strong>Get option prices from NSE:</strong> '
        '<a href="{url}" target="_blank">Open {asset} Option Chain on NSE ↗</a></div>'.format(
            url=NSE_CHAIN_URLS[asset], asset=asset),
        unsafe_allow_html=True
    )

lot = LOT_SIZES[asset]
total_units = num_lots * lot
step = float(STRIKE_STEP[asset])

# ── OPTION PRICE LOOKUP ───────────────────────────────────────────────────────
def lookup_option_price(chain_df, target_strike):
    if chain_df.empty:
        return None
    strikes = chain_df["strike"].values
    mask = np.isclose(strikes, target_strike, rtol=0, atol=step * 0.4)
    if not mask.any():
        return None
    price  = chain_df.loc[mask, "lastPrice"].values[0]
    volume = chain_df.loc[mask, "volume"].values[0] if "volume" in chain_df.columns else np.nan
    oi     = chain_df.loc[mask, "openInterest"].values[0] if "openInterest" in chain_df.columns else np.nan
    if price > 0 and (pd.isna(volume) or volume > 0 or (not pd.isna(oi) and oi > 0)):
        return float(round(price, 2))
    return None

c1, c2, c3 = st.columns(3)
with c1:
    default_strike = float(round(s0 / step) * step)
    strike = st.number_input("Strike Price (₹)", value=default_strike, step=step, format="%.2f")
with c2:
    live_call    = lookup_option_price(calls_df, strike)
    call_default = live_call if live_call is not None else round(s0 * 0.025, 2)
    call_source  = "🟢 Live" if live_call is not None else "🟡 Enter manually"
    c_mkt = st.number_input("Call Price (₹)  {}".format(call_source),
                            value=float(call_default), min_value=0.01, step=0.5, format="%.2f")
with c3:
    live_put    = lookup_option_price(puts_df, strike)
    put_default = live_put if live_put is not None else round(s0 * 0.018, 2)
    put_source  = "🟢 Live" if live_put is not None else "🟡 Enter manually"
    p_mkt = st.number_input("Put Price (₹)  {}".format(put_source),
                            value=float(put_default), min_value=0.01, step=0.5, format="%.2f")

# ── CALCULATIONS ──────────────────────────────────────────────────────────────
t               = days_to_expiry / 365.0
pv_k            = strike * np.exp(-r_rate * t)
synthetic_spot  = c_mkt - p_mkt + pv_k
spread_per_unit = s0 - synthetic_spot
fno_orders      = 2 * num_lots
spot_orders     = 2
total_brokerage = brokerage * (fno_orders + spot_orders)
stt_spot        = s0 * total_units * 0.001
stt_options     = (c_mkt + p_mkt) * total_units * 0.000625
total_friction  = total_brokerage + stt_spot + stt_options
gross_spread    = abs(spread_per_unit) * total_units
arb_threshold   = s0 * (arb_threshold_pct / 100)

# ── SIGNAL ────────────────────────────────────────────────────────────────────
if spread_per_unit > arb_threshold:
    signal_line, signal_color, strategy_desc, signal_type = "CONVERSION ARBITRAGE DETECTED", "#28a745", "Buy Spot  ·  Buy Put  ·  Sell Call", "conversion"
    net_pnl = gross_spread - total_friction
elif spread_per_unit < -arb_threshold:
    signal_line, signal_color, strategy_desc, signal_type = "REVERSAL ARBITRAGE DETECTED", "#dc3545", "Short Spot  ·  Sell Put  ·  Buy Call", "reversal"
    net_pnl = gross_spread - total_friction
else:
    signal_line, signal_color, strategy_desc, signal_type = "MARKET IS EFFICIENT — No Arbitrage", "#6c757d", "No Action", "none"
    net_pnl = -total_friction

pnl_is_profitable = net_pnl > 0

# ── METRICS ───────────────────────────────────────────────────────────────────
st.markdown("---")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Market Spot",      "₹{:,.2f}".format(s0))
m2.metric("Synthetic Price",  "₹{:,.2f}".format(synthetic_spot))
m3.metric("Arbitrage Gap",    "₹{:.2f}".format(abs(spread_per_unit)),
          delta="Threshold ₹{:.2f}".format(arb_threshold), delta_color="off")
m4.metric("Total Friction",   "₹{:,.2f}".format(total_friction))
m5.metric("Capital Required", "₹{:,.0f}".format(s0 * total_units * margin_pct))

st.markdown(
    '<div style="background-color:{c}; padding:14px; border-radius:10px; '
    'text-align:center; color:white; margin-top:12px;">'
    '<h2 style="margin:0; font-size:22px;">{s}</h2>'
    '<p style="margin:4px 0 0 0; font-size:15px; opacity:0.9;">Strategy: {d}</p>'
    '</div>'.format(c=signal_color, s=signal_line, d=strategy_desc),
    unsafe_allow_html=True
)

if signal_type != "none" and not pnl_is_profitable:
    st.markdown('<div class="warning-box">⚠️ <strong>Gap detected but NOT profitable after costs.</strong> Friction exceeds gross spread. Do not trade.</div>', unsafe_allow_html=True)

st.write("")
col_proof, col_graph = st.columns([1, 1.4])

with col_proof:
    st.subheader("📊 Execution Proof")
    st.markdown("**Strategy:** {}".format(strategy_desc))
    st.latex(r"C - P = S_0 - K \cdot e^{-rT} \quad \text{(Put-Call Parity)}")
    st.latex(r"\text{Gap} = S_0 - (C - P + K e^{-rT})")
    st.markdown("**Cost Breakdown:**")
    cost_df = pd.DataFrame({
        "Item": ["Brokerage ({} orders)".format(fno_orders + spot_orders), "STT on Spot", "STT on Options", "Total Friction"],
        "Amount (₹)": ["₹{:,.2f}".format(total_brokerage), "₹{:,.2f}".format(stt_spot),
                       "₹{:,.2f}".format(stt_options), "₹{:,.2f}".format(total_friction)]
    })
    st.dataframe(cost_df, hide_index=True, use_container_width=True)
    st.metric("Net Profit (after all costs)", "₹{:,.2f}".format(net_pnl),
              delta="Profitable ✅" if pnl_is_profitable else "Loss after costs ❌",
              delta_color="normal" if pnl_is_profitable else "inverse")
    st.caption("Across {:,} units ({} lot{} × {})".format(total_units, num_lots, "s" if num_lots > 1 else "", lot))

with col_graph:
    prices = np.linspace(s0 * 0.75, s0 * 1.25, 300)
    if signal_type == "conversion":
        spot_pnl  = (prices - s0) * total_units
        put_pnl   = (np.maximum(strike - prices, 0) - p_mkt) * total_units
        call_pnl  = (c_mkt - np.maximum(prices - strike, 0)) * total_units
        total_pnl = spot_pnl + put_pnl + call_pnl - total_friction
    elif signal_type == "reversal":
        spot_pnl  = (s0 - prices) * total_units
        put_pnl   = (p_mkt - np.maximum(strike - prices, 0)) * total_units
        call_pnl  = (np.maximum(prices - strike, 0) - c_mkt) * total_units
        total_pnl = spot_pnl + put_pnl + call_pnl - total_friction
    else:
        spot_pnl = put_pnl = call_pnl = total_pnl = np.zeros_like(prices)

    net_range_pad = max(abs(net_pnl) * 5, 500)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=prices, y=spot_pnl, mode="lines", name="Spot Leg",
                             line=dict(color="#1f77b4", width=1.5, dash="dot"), opacity=0.55, yaxis="y1"))
    fig.add_trace(go.Scatter(x=prices, y=put_pnl, mode="lines", name="Put Leg",
                             line=dict(color="#ff7f0e", width=1.5, dash="dot"), opacity=0.55, yaxis="y1"))
    fig.add_trace(go.Scatter(x=prices, y=call_pnl, mode="lines", name="Call Leg",
                             line=dict(color="#9467bd", width=1.5, dash="dot"), opacity=0.55, yaxis="y1"))
    fig.add_trace(go.Scatter(x=prices, y=total_pnl, mode="lines", name="Net P&L (right axis)",
                             line=dict(color=signal_color, width=3.5), yaxis="y2"))
    fig.add_shape(type="line", x0=prices[0], x1=prices[-1], y0=0, y1=0,
                  line=dict(color="gray", width=1, dash="dash"), yref="y2")
    fig.add_vline(x=s0, line_dash="dash", line_color="#333333", line_width=1,
                  annotation_text="Spot ₹{:,.0f}".format(s0), annotation_position="top right")
    fig.update_layout(
        title="Strategy Payoff at Expiry — Legs vs Net P&L",
        xaxis=dict(title=dict(text="Spot Price at Expiry (₹)"), tickformat=",.0f", showgrid=True, gridcolor="#e9ecef"),
        yaxis=dict(title=dict(text="Individual Leg P&L (₹)", font=dict(color="#555555")),
                   tickformat=",.0f", tickfont=dict(color="#555555"), showgrid=False),
        yaxis2=dict(title=dict(text="Net P&L (₹)", font=dict(color=signal_color)),
                    tickformat=",.0f", tickfont=dict(color=signal_color),
                    overlaying="y", side="right", range=[-net_range_pad, net_range_pad],
                    showgrid=True, gridcolor="#e9ecef", zeroline=True, zerolinecolor="gray"),
        height=360, margin=dict(t=45, b=40, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified", plot_bgcolor="#f8f9fa", paper_bgcolor="white",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("📌 Dotted = individual legs (left axis). Solid = Net P&L (right axis, zoomed). Net P&L is flat — payoff is locked.")

# ── SCENARIO TABLE ────────────────────────────────────────────────────────────
st.divider()
st.subheader("📉 Expiry Scenario Analysis")
st.caption("Individual legs vary with price, but Gross P&L and Net P&L are always locked.")

scenario_prices = {"Bear (−15%)": s0*0.85, "Bear (−10%)": s0*0.90, "At Strike": strike,
                   "At Money": s0, "Bull (+10%)": s0*1.10, "Bull (+15%)": s0*1.15}
rows = []
for label, st_price in scenario_prices.items():
    if signal_type == "conversion":
        s_leg = (st_price - s0) * total_units
        p_leg = (max(strike - st_price, 0) - p_mkt) * total_units
        c_leg = (c_mkt - max(st_price - strike, 0)) * total_units
    elif signal_type == "reversal":
        s_leg = (s0 - st_price) * total_units
        p_leg = (p_mkt - max(strike - st_price, 0)) * total_units
        c_leg = (max(st_price - strike, 0) - c_mkt) * total_units
    else:
        s_leg = p_leg = c_leg = 0.0
    gross = gross_spread if signal_type != "none" else 0.0
    net   = gross - total_friction
    rows.append({"Scenario": label, "Expiry Price": "₹{:,.0f}".format(st_price),
                 "Spot Leg (₹)": "₹{:,.2f}".format(s_leg), "Put Leg (₹)": "₹{:,.2f}".format(p_leg),
                 "Call Leg (₹)": "₹{:,.2f}".format(c_leg), "Gross P&L (₹)": "₹{:,.2f}".format(gross),
                 "Friction (₹)": "−₹{:,.2f}".format(total_friction), "Net P&L (₹)": "₹{:,.2f}".format(net)})

st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
st.info("**Why is Net P&L the same in every row?** — The arbitrage profit is locked at inception by put-call parity. Gross P&L = ₹{:,.2f} (gap × units). Net P&L = ₹{:,.2f} (Gross − Friction) — identical to Net Profit above.".format(gross_spread, net_pnl))

# ── BREAK-EVEN & SENSITIVITY ──────────────────────────────────────────────────
if signal_type != "none" and abs(spread_per_unit) > 0:
    st.divider()
    st.subheader("🔍 Break-Even & Sensitivity")
    col_be1, col_be2 = st.columns(2)
    with col_be1:
        break_even_lots = None
        for n in range(1, 501):
            tu = n * lot
            fric = brokerage*(2*n+2) + s0*tu*0.001 + (c_mkt+p_mkt)*tu*0.000625
            if abs(spread_per_unit) * tu >= fric:
                break_even_lots = n
                break
        if break_even_lots:
            st.metric("Break-Even Lots", "{} lots".format(break_even_lots),
                      delta="You selected {} lots".format(num_lots),
                      delta_color="normal" if num_lots >= break_even_lots else "inverse")
        else:
            st.warning("Cannot be profitable even with 500 lots.")
    with col_be2:
        lot_range = list(range(1, min(num_lots*4+1, 51)))
        pnl_by_lots = [abs(spread_per_unit)*n*lot - brokerage*(2*n+2) - s0*n*lot*0.001 - (c_mkt+p_mkt)*n*lot*0.000625 for n in lot_range]
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(x=lot_range, y=pnl_by_lots,
                              marker_color=[signal_color if p > 0 else "#dc3545" for p in pnl_by_lots]))
        fig2.add_hline(y=0, line_dash="dash", line_color="gray")
        fig2.update_layout(title="Net P&L vs Number of Lots", xaxis_title="Number of Lots",
                           yaxis=dict(title="Net P&L (₹)", tickformat=",.0f"),
                           height=260, margin=dict(t=35, b=30, l=0, r=0),
                           plot_bgcolor="#f8f9fa", paper_bgcolor="white", showlegend=False)
        st.plotly_chart(fig2, use_container_width=True)

st.divider()
st.caption("⚠️ Disclaimer: For educational and research purposes only. Arbitrage windows last milliseconds in real markets. Not financial advice. | Built at IIT Roorkee · Dept. of Management Studies")
