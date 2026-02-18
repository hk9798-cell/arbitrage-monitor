import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go

# --- 1. CONFIG & UI STYLING ---
st.set_page_config(page_title="Arbitrage Monitor", layout="wide")

st.markdown("""
    <style>
    label[data-testid="stWidgetLabel"] p { font-weight: bold !important; font-size: 16px !important; }
    div[data-testid="stMetricLabel"] p { font-weight: bold !important; font-size: 16px !important; }
    div[data-testid="stMetricValue"] { font-size: 28px; color: #1f77b4; font-weight: bold; }
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

# --- 3. FIXING THE DATA ENGINE (NSE Specific) ---
@st.cache_data(ttl=15)
def get_market_data(ticker_symbol):
    try:
        stock = yf.Ticker(ticker_symbol)
        # Fetching spot price
        hist = stock.history(period="1d")
        spot = hist['Close'].iloc[-1] if not hist.empty else 0.0
        
        # Fixing the Expiry Fetch for NSE
        options = stock.options
        if options:
            expiry = options[0] 
            chain = stock.option_chain(expiry)
            return round(spot, 2), chain.calls, chain.puts, expiry
        return round(spot, 2), pd.DataFrame(), pd.DataFrame(), "No Expiry Found"
    except Exception as e:
        return 0.0, pd.DataFrame(), pd.DataFrame(), "Connection Error"

s0, calls_df, puts_df, current_expiry = get_market_data(ticker_map[asset])
lot = lot_sizes[asset]
total_units = num_lots * lot
step_val = strike_steps[asset]

# --- 4. PRICE LOOKUP (Correcting the drastic difference) ---
c1, c2, c3 = st.columns(3)
with c1:
    default_strike = float(round(s0 / step_val) * step_val)
    strike = st.number_input("Strike Price", value=default_strike, step=step_val)

with c2:
    val_c = 0.0
    # Search the live chain for the strike
    if not calls_df.empty:
        match = calls_df[calls_df['strike'] == strike]
        if not match.empty:
            val_c = match['lastPrice'].values[0]
    
    # REMOVED the math fallback to ensure you see real LTP or 0
    c_mkt = st.number_input("Call Price (LTP)", value=float(val_c), key=f"c_{asset}_{strike}")

with c3:
    val_p = 0.0
    if not puts_df.empty:
        match = puts_df[puts_df['strike'] == strike]
        if not match.empty:
            val_p = match['lastPrice'].values[0]
            
    p_mkt = st.number_input("Put Price (LTP)", value=float(val_p), key=f"p_{asset}_{strike}")

# --- 5. CALCULATIONS & UI ---
t = days_to_expiry / 365
pv_k = strike * np.exp(-r_rate * t)
synthetic_spot = c_mkt - p_mkt + pv_k
spread_per_unit = s0 - synthetic_spot
total_friction = (brokerage * 3 * num_lots) + (s0 * total_units * 0.001)
capital_req = (s0 * total_units) * margin_pct

# Alert Logic
if spread_per_unit > 0.5:
    sig_line, sig_col, strategy = "CONVERSION ARBITRAGE", "#28a745", "Buy Spot, Buy Put, Sell Call"
    pnl = (spread_per_unit * total_units) - total_friction
elif spread_per_unit < -0.5:
    sig_line, sig_col, strategy = "REVERSAL ARBITRAGE", "#dc3545", "Short Spot, Sell Put, Buy Call"
    pnl = (abs(spread_per_unit) * total_units) - total_friction
else:
    sig_line, sig_col, pnl, strategy = "EFFICIENT MARKET", "#6c757d", 0.0, "None"

m1, m2, m3, m4 = st.columns(4)
m1.metric("Market Spot", f"₹{s0:,.2f}")
m2.metric("Synthetic", f"₹{synthetic_spot:,.2f}")
m3.metric("Gap", f"₹{abs(spread_per_unit):.2f}")
m4.metric("Capital", f"₹{capital_req:,.0f}")

st.markdown(f'<div style="background-color:{sig_col}; padding:15px; border-radius:10px; text-align:center; color:white;"><h2>{sig_line}</h2><p>Expiry: {current_expiry}</p></div>', unsafe_allow_html=True)

st.subheader("📊 Execution Proof")
st.latex(r"P = Units \times [ (S_{T} - S_{0}) + (K - S_{T})^{+} - (S_{T} - K)^{+} + (C - P) ]")
st.metric("Net Profit", f"₹{pnl:,.2f}")

# Payoff Chart
prices = np.linspace(s0*0.95, s0*1.05, 10)
fig = go.Figure(go.Scatter(x=prices, y=[pnl]*10, mode='lines', line=dict(color=sig_col, width=4)))
fig.update_layout(title="Payoff Graph", height=250, margin=dict(t=30, b=0, l=0, r=0))
st.plotly_chart(fig, use_container_width=True)
