import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go

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
    </style>
""", unsafe_allow_html=True)

st.title("🏛️ Cross-Asset Arbitrage Opportunity Monitor")

TICKER_MAP = {"NIFTY": "^NSEI", "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "SBIN": "SBIN.NS", "INFY": "INFY.NS"}  # yfinance fallback only
LOT_SIZES = {"NIFTY": 65, "RELIANCE": 250, "TCS": 175, "SBIN": 1500, "INFY": 400}
STRIKE_STEP = {"NIFTY": 50, "RELIANCE": 20, "TCS": 50, "SBIN": 5, "INFY": 20}
FALLBACK_SPOTS = {"NIFTY": 24500.0, "RELIANCE": 1280.0, "TCS": 3850.0, "SBIN": 810.0, "INFY": 1580.0}

with st.sidebar:
    st.header("⚙️ Parameters")
    asset = st.selectbox("Select Asset", list(TICKER_MAP.keys()))
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

import requests

# NSE symbol map (used for NSE API)
NSE_SYMBOL_MAP = {
    "NIFTY":    "NIFTY",
    "RELIANCE": "RELIANCE",
    "TCS":      "TCS",
    "SBIN":     "SBIN",
    "INFY":     "INFY",
}

NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.nseindia.com/",
    "Accept": "application/json, text/plain, /",
}

@st.cache_data(ttl=60, show_spinner=False)
def get_nse_session_cookies():
    """Warm up NSE session to get valid cookies (required for API calls)."""
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=NSE_HEADERS, timeout=10)
        return dict(session.cookies)
    except Exception:
        return {}

@st.cache_data(ttl=60, show_spinner=False)
def get_market_data(asset_name):
    """
    Fetch live spot price and option chain from NSE India API.
    Falls back to yfinance as secondary, then static fallback.
    Returns (spot, calls_df, puts_df, expiry_date, error_msg).
    """
    symbol = NSE_SYMBOL_MAP[asset_name]

    # ── PRIMARY: NSE India API ─────────────────────────────────────────────
    try:
        cookies = get_nse_session_cookies()
        is_index = (asset_name == "NIFTY")

        if is_index:
            url = "https://www.nseindia.com/api/option-chain-indices?symbol={}".format(symbol)
        else:
            url = "https://www.nseindia.com/api/option-chain-equities?symbol={}".format(symbol)

        resp = requests.get(url, headers=NSE_HEADERS, cookies=cookies, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        spot = float(data["records"]["underlyingValue"])
        expiries = data["records"]["expiryDates"]
        expiry = expiries[0]

        calls_rows, puts_rows = [], []
        for rec in data["records"]["data"]:
            if rec.get("expiryDate") != expiry:
                continue
            k = float(rec["strikePrice"])
            if "CE" in rec:
                ce = rec["CE"]
                calls_rows.append({
                    "strike":        k,
                    "lastPrice":     float(ce.get("lastPrice", 0)),
                    "openInterest":  float(ce.get("openInterest", 0)),
                    "volume":        float(ce.get("totalTradedVolume", 0)),
                    "impliedVolatility": float(ce.get("impliedVolatility", 0)),
                })
            if "PE" in rec:
                pe = rec["PE"]
                puts_rows.append({
                    "strike":        k,
                    "lastPrice":     float(pe.get("lastPrice", 0)),
                    "openInterest":  float(pe.get("openInterest", 0)),
                    "volume":        float(pe.get("totalTradedVolume", 0)),
                    "impliedVolatility": float(pe.get("impliedVolatility", 0)),
                })

        calls_df = pd.DataFrame(calls_rows)
        puts_df  = pd.DataFrame(puts_rows)
        return round(spot, 2), calls_df, puts_df, expiry, None

    except Exception as nse_err:
        pass  # Try yfinance fallback

    # ── SECONDARY: yfinance ────────────────────────────────────────────────
    try:
        ticker_sym = {"NIFTY": "^NSEI", "RELIANCE": "RELIANCE.NS",
                      "TCS": "TCS.NS", "SBIN": "SBIN.NS", "INFY": "INFY.NS"}[asset_name]
        stock = yf.Ticker(ticker_sym)
        hist  = stock.history(period="2d")
        if hist.empty:
            raise ValueError("yfinance returned empty history.")
        spot = float(round(hist["Close"].iloc[-1], 2))
        if stock.options:
            expiry = stock.options[0]
            chain  = stock.option_chain(expiry)
            calls  = chain.calls.copy()
            puts   = chain.puts.copy()
            calls["strike"] = calls["strike"].astype(float)
            puts["strike"]  = puts["strike"].astype(float)
            return spot, calls, puts, expiry, "NSE API unavailable — using yfinance (15min delay)"
        return spot, pd.DataFrame(), pd.DataFrame(), None, "yfinance: no options chain available."
    except Exception as yf_err:
        return (FALLBACK_SPOTS[asset_name], pd.DataFrame(), pd.DataFrame(), None,
                "All live sources failed. Using static fallback price.")

with st.spinner("Fetching live data for {} from NSE...".format(asset)):
    s0, calls_df, puts_df, expiry_date, fetch_error = get_market_data(asset)

if fetch_error:
    st.warning("⚠️  {}  |  Spot: ₹{:,.2f}".format(fetch_error, s0))
if expiry_date:
    st.caption("📅 NSE option chain loaded — Expiry: *{}*  |  Spot: ₹{:,.2f}".format(expiry_date, s0))

lot = LOT_SIZES[asset]
total_units = num_lots * lot
step = float(STRIKE_STEP[asset])

def lookup_option_price(chain_df, target_strike):
    if chain_df.empty:
        return None
    strikes = chain_df["strike"].values
    mask = np.isclose(strikes, target_strike, rtol=0, atol=step * 0.4)
    if not mask.any():
        return None
    price = chain_df.loc[mask, "lastPrice"].values[0]
    volume = chain_df.loc[mask, "volume"].values[0] if "volume" in chain_df.columns else np.nan
    oi = chain_df.loc[mask, "openInterest"].values[0] if "openInterest" in chain_df.columns else np.nan
    if price > 0 and (pd.isna(volume) or volume > 0 or (not pd.isna(oi) and oi > 0)):
        return float(round(price, 2))
    return None

c1, c2, c3 = st.columns(3)
with c1:
    default_strike = float(round(s0 / step) * step)
    strike = st.number_input("Strike Price (₹)", value=default_strike, step=step, format="%.2f")
with c2:
    live_call = lookup_option_price(calls_df, strike)
    call_default = live_call if live_call is not None else round(s0 * 0.025, 2)
    call_source = "🟢 Live" if live_call is not None else "🟡 Estimated"
    c_mkt = st.number_input("Call Price (₹)  {}".format(call_source),
                            value=float(call_default), min_value=0.01, step=0.5, format="%.2f")
with c3:
    live_put = lookup_option_price(puts_df, strike)
    put_default = live_put if live_put is not None else round(s0 * 0.018, 2)
    put_source = "🟢 Live" if live_put is not None else "🟡 Estimated"
    p_mkt = st.number_input("Put Price (₹)  {}".format(put_source),
                            value=float(put_default), min_value=0.01, step=0.5, format="%.2f")

t = days_to_expiry / 365.0
pv_k = strike * np.exp(-r_rate * t)
synthetic_spot = c_mkt - p_mkt + pv_k
spread_per_unit = s0 - synthetic_spot

fno_orders = 2 * num_lots
spot_orders = 2
total_brokerage = brokerage * (fno_orders + spot_orders)
stt_spot = s0 * total_units * 0.001
stt_options = (c_mkt + p_mkt) * total_units * 0.000625
total_friction = total_brokerage + stt_spot + stt_options
gross_spread = abs(spread_per_unit) * total_units
arb_threshold = s0 * (arb_threshold_pct / 100)

if spread_per_unit > arb_threshold:
    signal_line   = "CONVERSION ARBITRAGE DETECTED"
    signal_color  = "#28a745"
    strategy_desc = "Buy Spot  ·  Buy Put  ·  Sell Call"
    signal_type   = "conversion"
    net_pnl = gross_spread - total_friction
elif spread_per_unit < -arb_threshold:
    signal_line   = "REVERSAL ARBITRAGE DETECTED"
    signal_color  = "#dc3545"
    strategy_desc = "Short Spot  ·  Sell Put  ·  Buy Call"
    signal_type   = "reversal"
    net_pnl = gross_spread - total_friction
else:
    signal_line   = "MARKET IS EFFICIENT — No Arbitrage"
    signal_color  = "#6c757d"
    strategy_desc = "No Action"
    signal_type   = "none"
    net_pnl = -total_friction

pnl_is_profitable = net_pnl > 0

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
    st.markdown(
        '<div class="warning-box">⚠️ <strong>Gap detected but NOT profitable after costs.</strong> '
        'Friction exceeds gross spread. Do not trade.</div>',
        unsafe_allow_html=True
    )

st.write("")
col_proof, col_graph = st.columns([1, 1.4])

with col_proof:
    st.subheader("📊 Execution Proof")
    st.markdown("*Strategy:* {}".format(strategy_desc))
    st.latex(r"C - P = S_0 - K \cdot e^{-rT} \quad \text{(Put-Call Parity)}")
    st.latex(r"\text{Gap} = S_0 - (C - P + K e^{-rT})")
    st.markdown("*Cost Breakdown:*")
    cost_df = pd.DataFrame({
        "Item": ["Brokerage ({} orders)".format(fno_orders + spot_orders),
                 "STT on Spot", "STT on Options", "Total Friction"],
        "Amount (₹)": [
            "₹{:,.2f}".format(total_brokerage),
            "₹{:,.2f}".format(stt_spot),
            "₹{:,.2f}".format(stt_options),
            "₹{:,.2f}".format(total_friction),
        ]
    })
    st.dataframe(cost_df, hide_index=True, use_container_width=True)
    st.metric(
        "Net Profit (after all costs)", "₹{:,.2f}".format(net_pnl),
        delta="Profitable ✅" if pnl_is_profitable else "Loss after costs ❌",
        delta_color="normal" if pnl_is_profitable else "inverse",
    )
    st.caption("Across {:,} units ({} lot{} × {})".format(
        total_units, num_lots, "s" if num_lots > 1 else "", lot))

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
        spot_pnl  = np.zeros_like(prices)
        put_pnl   = np.zeros_like(prices)
        call_pnl  = np.zeros_like(prices)
        total_pnl = np.zeros_like(prices)

    net_range_pad = max(abs(net_pnl) * 5, 500)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=prices, y=spot_pnl, mode="lines", name="Spot Leg",
                             line=dict(color="#1f77b4", width=1.5, dash="dot"),
                             opacity=0.55, yaxis="y1"))
    fig.add_trace(go.Scatter(x=prices, y=put_pnl, mode="lines", name="Put Leg",
                             line=dict(color="#ff7f0e", width=1.5, dash="dot"),
                             opacity=0.55, yaxis="y1"))
    fig.add_trace(go.Scatter(x=prices, y=call_pnl, mode="lines", name="Call Leg",
                             line=dict(color="#9467bd", width=1.5, dash="dot"),
                             opacity=0.55, yaxis="y1"))
    fig.add_trace(go.Scatter(x=prices, y=total_pnl, mode="lines", name="Net P&L (right axis)",
                             line=dict(color=signal_color, width=3.5), yaxis="y2"))
    fig.add_shape(type="line", x0=prices[0], x1=prices[-1], y0=0, y1=0,
                  line=dict(color="gray", width=1, dash="dash"), yref="y2")
    fig.add_vline(x=s0, line_dash="dash", line_color="#333333", line_width=1,
                  annotation_text="Spot ₹{:,.0f}".format(s0), annotation_position="top right")
    fig.update_layout(
        title="Strategy Payoff at Expiry — Legs vs Net P&L",
        xaxis=dict(
            title=dict(text="Spot Price at Expiry (₹)"),
            tickformat=",.0f", showgrid=True, gridcolor="#e9ecef"
        ),
        yaxis=dict(
            title=dict(text="Individual Leg P&L (₹)", font=dict(color="#555555")),
            tickformat=",.0f", tickfont=dict(color="#555555"), showgrid=False
        ),
        yaxis2=dict(
            title=dict(text="Net P&L (₹)", font=dict(color=signal_color)),
            tickformat=",.0f", tickfont=dict(color=signal_color),
            overlaying="y", side="right",
            range=[-net_range_pad, net_range_pad],
            showgrid=True, gridcolor="#e9ecef",
            zeroline=True, zerolinecolor="gray"
        ),
        height=360, margin=dict(t=45, b=40, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified", plot_bgcolor="#f8f9fa", paper_bgcolor="white",
    )
    st.plotly_chart(fig, use_container_width=True)
    st.caption("📌 Dotted lines = individual legs (left axis). Solid line = Net P&L (right axis, zoomed). "
               "Net P&L is flat — payoff is locked regardless of expiry price.")

st.divider()
st.subheader("📉 Expiry Scenario Analysis")
st.caption("Leg-by-leg P&L at different expiry prices. Gross and Net P&L should be identical across all rows.")

scenario_prices = {
    "Bear (−15%)": s0 * 0.85,
    "Bear (−10%)": s0 * 0.90,
    "At Strike":   strike,
    "At Money":    s0,
    "Bull (+10%)": s0 * 1.10,
    "Bull (+15%)": s0 * 1.15,
}

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

    # gross_spread is the locked arbitrage profit, already correctly computed
    # from put-call parity above. It does NOT vary with expiry price.
    # Individual legs are shown for educational purposes only.
    gross = gross_spread if signal_type != "none" else 0.0
    net   = gross - total_friction

    rows.append({
        "Scenario":      label,
        "Expiry Price":  "₹{:,.0f}".format(st_price),
        "Spot Leg (₹)":  "₹{:,.2f}".format(s_leg),
        "Put Leg (₹)":   "₹{:,.2f}".format(p_leg),
        "Call Leg (₹)":  "₹{:,.2f}".format(c_leg),
        "Gross P&L (₹)": "₹{:,.2f}".format(gross),
        "Friction (₹)":  "−₹{:,.2f}".format(total_friction),
        "Net P&L (₹)":   "₹{:,.2f}".format(net),
    })

st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
st.info(
    "*Why is Net P&L the same in every row?* — "
    "The arbitrage profit is locked at inception by put-call parity and does not depend on "
    "where the stock expires. The individual legs (Spot/Put/Call) move in opposite directions "
    "and partially cancel each other — but the Gross P&L is always pinned to "
    "₹{:,.2f} (= gap × units), and Net P&L is always ₹{:,.2f} (= Gross − Friction). "
    "This matches Net Profit above exactly. That is the core proof of arbitrage.".format(
        gross_spread, net_pnl)
)

if signal_type != "none" and abs(spread_per_unit) > 0:
    st.divider()
    st.subheader("🔍 Break-Even & Sensitivity")
    col_be1, col_be2 = st.columns(2)

    with col_be1:
        break_even_lots = None
        for n in range(1, 501):
            tu     = n * lot
            b_cost = brokerage * (2 * n + 2)
            s_stt  = s0 * tu * 0.001
            o_stt  = (c_mkt + p_mkt) * tu * 0.000625
            fric   = b_cost + s_stt + o_stt
            gross_ = abs(spread_per_unit) * tu
            if gross_ >= fric:
                break_even_lots = n
                break
        if break_even_lots:
            st.metric("Break-Even Lots", "{} lots".format(break_even_lots),
                      delta="You selected {} lots".format(num_lots),
                      delta_color="normal" if num_lots >= break_even_lots else "inverse")
        else:
            st.warning("Cannot be profitable even with 500 lots.")

    with col_be2:
        lot_range   = list(range(1, min(num_lots * 4 + 1, 51)))
        pnl_by_lots = []
        for n in lot_range:
            tu     = n * lot
            b_cost = brokerage * (2 * n + 2)
            s_stt  = s0 * tu * 0.001
            o_stt  = (c_mkt + p_mkt) * tu * 0.000625
            fric   = b_cost + s_stt + o_stt
            pnl_by_lots.append(abs(spread_per_unit) * tu - fric)
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            x=lot_range, y=pnl_by_lots,
            marker_color=[signal_color if p > 0 else "#dc3545" for p in pnl_by_lots],
        ))
        fig2.add_hline(y=0, line_dash="dash", line_color="gray")
        fig2.update_layout(
            title="Net P&L vs Number of Lots",
            xaxis_title="Number of Lots",
            yaxis=dict(title="Net P&L (₹)", tickformat=",.0f"),
            height=260, margin=dict(t=35, b=30, l=0, r=0),
            plot_bgcolor="#f8f9fa", paper_bgcolor="white", showlegend=False,
        )
        st.plotly_chart(fig2, use_container_width=True)

st.divider()
st.caption(
    "⚠️ Disclaimer: For educational and research purposes only. "
    "Arbitrage windows last milliseconds in real markets. "
    "Not financial advice. | Built at IIT Roorkee · Dept. of Management Studies"
)
