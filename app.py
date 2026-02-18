import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go

# --- 1. CONFIG & UI STYLING ---
st.set_page_config(page_title="Arbitrage Monitor", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    label[data-testid="stWidgetLabel"] p { font-weight: bold !important; font-size: 16px !important; }
    div[data-testid="stMetricLabel"] p { font-weight: bold !important; font-size: 16px !important; }
    div[data-testid="stMetricValue"] { font-size: 28px; color: #1f77b4; font-weight: bold; }
    .stTable { border-radius: 10px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }
    </style>
    """, unsafe_allow_html=True)

st.title("🏛️ Cross-Asset Arbitrage Opportunity Monitor")

# --- 2. ASSET MASTER DATA ---
ticker_map = {"NIFTY": "^NSEI", "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "SBIN": "SBIN.NS", "INFY": "INFY.NS"}
lot_sizes = {"NIFTY": 65, "RELIANCE": 250, "TCS": 175, "SBIN": 1500, "INFY": 400}
strike_steps = {"NIFTY": 50.0, "RELIANCE": 20.0, "TCS": 20.0, "SBIN": 5.0, "INFY": 10.0}

with st.sidebar:
    st.header("⚙️ Parameters")
    asset = st.selectbox("Select Asset", list(ticker_map.keys()))
    num_lots = st.number_input("Number of Lots", min_value=1, value=1)
    r_rate = st.slider("Risk-Free Rate (%)", 4.0, 10.0, 6.75) / 100
    days_to_expiry = st.number_input("Days to Expiry", value=15, min_value=1)
    st.divider()
    brokerage = st.number_input("Brokerage/Side (₹)", value=20.0)
    margin_pct = st.slider("Margin Requirement (%)", 10, 40, 20) / 100

# --- 3. DATA ENGINE (With Smart Recovery) ---
@st.cache_data(ttl=10)
def get_market_data(ticker_symbol):
    try:
        stock = yf.Ticker(ticker_symbol)
        # Fast spot price fetch
        data = stock.fast_info
        spot = data['last_price'] if 'last_price' in data else 0.0
        
        options = stock.options
        if options:
            expiry = options[0]
            chain = stock.option_chain(expiry)
            return round(spot, 2), chain.calls, chain.puts, expiry
        return round(spot, 2), pd.DataFrame(), pd.DataFrame(), "Waiting for Market..."
    except:
        return 0.0, pd.DataFrame(), pd.DataFrame(), "Data Link Error"

s0, calls_df, puts_df, current_expiry = get_market_data(ticker_map[asset])
lot = lot_sizes[asset]
total_units = num_lots * lot
step_val = strike_steps[asset]

# --- 4. PRICE LOOKUP ---
c1, c2, c3 = st.columns(3)
with c1:
    default_strike = float(round(s0 / step_val) * step_val) if s0 > 0 else 25800.0
    strike = st.number_input("Strike Price", value=default_strike, step=step_val)

with c2:
    val_c = 0.0
    if not calls_df.empty:
        match = calls_df[calls_df['strike'] == strike]
        if not match.empty:
            val_c = match['lastPrice'].values[0]
    
    # If the live lookup fails, we show a 'zero' but allow you to type in manually 
    # as seen in your Nifty app screenshot (₹174.50)
    c_mkt = st.number_input("Call Price (LTP)", value=float(val_c), key=f"c_{asset}_{strike}")

with c3:
    val_p = 0.0
    if not puts_df.empty:
        match = puts_df[puts_df['strike'] == strike]
        if not match.empty:
            val_p = match['lastPrice'].values[0]
            
    p_mkt = st.number_input("Put Price (LTP)", value=float(val_p), key=f"p_{asset}_{strike}")

# --- 5. CALCULATIONS ---
t = days_to_expiry / 365
pv_k = strike * np.exp(-r_rate * t)
synthetic_spot = c_mkt - p_mkt + pv_k
spread_per_unit = s0 - synthetic_spot
total_friction = (brokerage * 3 * num_lots) + (s0 * total_units * 0.001)
capital_req = (s0 * total_units) * margin_pct

if spread_per_unit > 0.5:
    sig_line, sig_col, strategy = "CONVERSION ARBITRAGE DETECTED", "#28a745", "Buy Spot, Buy Put, Sell Call"
    pnl = (spread_per_unit * total_units) - total_friction
elif spread_per_unit < -0.5:
    sig_line, sig_col, strategy = "REVERSAL ARBITRAGE DETECTED", "#dc3545", "Short Spot, Sell Put, Buy Call"
    pnl = (abs(spread_per_unit) * total_units) - total_friction
else:
    sig_line, sig_col, pnl, strategy = "MARKET IS EFFICIENT", "#6c757d", 0.0, "No Action Required"

# --- 6. UI DISPLAY ---
m1, m2, m3, m4 = st.columns(4)
m1.metric("Market Spot", f"₹{s0:,.2f}")
m2.metric("Synthetic Price", f"₹{synthetic_spot:,.2f}")
m3.metric("Arbitrage Gap", f"₹{abs(spread_per_unit):.2f}")
m4.metric("Capital Req.", f"₹{capital_req:,.0f}")

st.markdown(f'<div style="background-color:{sig_col}; padding:15px; border-radius:10px; text-align:center; color:white;"><h2>{sig_line}</h2><p>Expiry: {current_expiry}</p></div>', unsafe_allow_html=True)

st.write("")
col_proof, col_graph = st.columns([1, 1.2])

with col_proof:
    st.subheader("📊 Execution Proof")
    st.write(f"*Strategy:* {strategy}")
    st.latex(r"P = Units \times [ (S_{T} - S_{0}) + (K - S_{T})^{+} - (S_{T} - K)^{+} + (C - P) ]")
    st.metric("Net Profit", f"₹{pnl:,.2f}")

with col_graph:
    prices = np.linspace(s0*0.98, s0*1.02, 10) if s0 > 0 else np.linspace(25000, 26000, 10)
    fig = go.Figure(go.Scatter(x=prices, y=[pnl]*10, mode='lines', line=dict(color=sig_col, width=4)))
    fig.update_layout(title="Risk-Neutral Payoff", height=250, margin=dict(t=30, b=0, l=0, r=0))
    st.plotly_chart(fig, use_container_width=True)

# --- 7. RESTORED SCENARIO TABLE ---
st.divider()
st.subheader("📉 Expiry Scenario Analysis")
scenarios = [s0 * 0.95, s0, s0 * 1.05] if s0 > 0 else [25000, 25800, 26500]
pdf = [{"Price at Expiry": f"₹{p:,.0f}", "Lot Size": lot, "Total Units": total_units, "TOTAL NET": f"₹{pnl:,.2f}"} for p in scenarios]
st.table(pd.DataFrame(pdf))
