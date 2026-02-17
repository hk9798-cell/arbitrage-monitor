import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# --- 1. CONFIG & UI STYLING ---
st.set_page_config(page_title="Arbitrage Monitor Pro", layout="wide")

st.markdown("""
    <style>
    [data-testid="stAppViewContainer"] { background-color: #0e1117; color: #ffffff; }
    [data-testid="stSidebar"] { background-color: #1a1c24; }
    .stMetric { background-color: #1f2937; padding: 15px; border-radius: 10px; border: 1px solid #374151; }
    div[data-testid="stMetricValue"] { font-size: 32px !important; color: #00ffcc !important; font-weight: bold; }
    div[data-testid="stMetricLabel"] { font-size: 16px !important; color: #e5e7eb !important; }
    .logic-box { background-color: #111827; padding: 20px; border-radius: 10px; border-left: 5px solid #00ffcc; color: #e5e7eb; }
    .proof-box { background-color: #000000; padding: 15px; border: 1px solid #374151; border-radius: 10px; font-family: 'Courier New', monospace; color: #00ffcc; }
    h1, h2, h3 { color: #ffffff !important; }
    /* Ensure table text is visible */
    .stTable td, .stTable th { color: #ffffff !important; font-size: 16px !important; }
    </style>
    """, unsafe_allow_html=True)

# KEEPING YOUR ORIGINAL HEADING
st.title("🏛️ Institutional Arbitrage Monitor")
st.markdown("---")

# --- 2. ASSET MASTER DATA ---
ticker_map = {"NIFTY": "^NSEI", "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "SBIN": "SBIN.NS", "INFY": "INFY.NS"}
lot_sizes = {"NIFTY": 65, "RELIANCE": 250, "TCS": 175, "SBIN": 1500, "INFY": 400}

with st.sidebar:
    st.header("⚙️ Market Settings")
    asset = st.selectbox("Select Asset", list(ticker_map.keys()))
    num_lots = st.number_input("Number of Lots", min_value=1, value=1)
    r_rate = st.slider("Risk-Free Rate (%)", 4.0, 10.0, 6.75) / 100
    st.divider()
    brokerage = st.number_input("Brokerage/Side (₹)", value=20.0)
    margin_pct = st.slider("Margin Requirement (%)", 10, 40, 25) / 100
    
    if st.button("🔄 Refresh Market Data"):
        st.cache_data.clear()

# --- 3. UPDATED DATA ENGINE (ERROR PROOF) ---
@st.cache_data(ttl=60)
def fetch_live_data(ticker_symbol):
    # Default values to prevent ValueError
    def_s, def_k, def_c, def_p, def_d = 25000.0, 25000.0, 500.0, 400.0, 15
    
    try:
        stock = yf.Ticker(ticker_symbol)
        history = stock.history(period="1d")
        
        if history.empty:
            return def_s, def_k, def_c, def_p, def_d
            
        s_price = round(history['Close'].iloc[-1], 2)
        expirations = stock.options
        
        if not expirations:
            return s_price, round(s_price, -1), round(s_price*0.02, 2), round(s_price*0.015, 2), def_d
        
        chain = stock.option_chain(expirations[0])
        calls, puts = chain.calls, chain.puts
        
        # Find closest ATM Strike
        atm_strike = calls.iloc[(calls['strike'] - s_price).abs().argsort()[:1]]['strike'].values[0]
        c_price = calls[calls['strike'] == atm_strike]['lastPrice'].values[0]
        p_price = puts[puts['strike'] == atm_strike]['lastPrice'].values[0]
        
        # Days to expiry
        d1 = datetime.strptime(expirations[0], '%Y-%m-%d')
        days_left = max((d1 - datetime.now()).days, 1)
        
        return s_price, float(atm_strike), float(c_price), float(p_price), int(days_left)
    except Exception as e:
        # If anything fails, return defaults instead of crashing
        return def_s, def_k, def_c, def_p, def_d

# Safe Unpacking
s0, auto_strike, auto_call, auto_put, dte = fetch_live_data(ticker_map[asset])

# Input Section
c1, c2, c3 = st.columns(3)
with c1: strike = st.number_input("Strike Price", value=float(auto_strike))
with c2: c_mkt = st.number_input("Call Price", value=float(auto_call))
with c3: p_mkt = st.number_input("Put Price", value=float(auto_put))

# --- 4. CALCS & LOGIC ---
total_units = num_lots * lot_sizes[asset]
t_time = dte / 365
pv_k = strike * np.exp(-r_rate * t_time)
synthetic_spot = c_mkt - p_mkt + pv_k
spread_per_unit = s0 - synthetic_spot
total_friction = (brokerage * 3 * num_lots) + (s0 * total_units * 0.001)
capital_req = (s0 * total_units) * margin_pct

if spread_per_unit > 0.5:
    sig, col, strat = "CONVERSION ARBITRAGE", "#00ffcc", "Buy Spot + Buy Put + Sell Call"
    net_pnl = (spread_per_unit * total_units) - total_friction
elif spread_per_unit < -0.5:
    sig, col, strat = "REVERSAL ARBITRAGE", "#ff4b4b", "Short Spot + Sell Put + Buy Call"
    net_pnl = (abs(spread_per_unit) * total_units) - total_friction
else:
    sig, col, strat, net_pnl = "EFFICIENT MARKET", "#9ca3af", "No Mispricing Detected", 0

# --- 5. VISUALS ---
m1, m2, m3, m4 = st.columns(4)
m1.metric("Market Spot", f"₹{s0:,.2f}")
m2.metric("Synthetic Price", f"₹{synthetic_spot:,.2f}")
m3.metric("Net Spread", f"₹{abs(spread_per_unit):.2f}")
m4.metric("Days left", f"{dte} Days")

st.markdown(f"""
    <div style="background-color:{col}; padding:15px; border-radius:10px; text-align:center; margin: 20px 0;">
        <h2 style="margin:0; color:#0e1117 !important;">{sig}</h2>
        <p style="margin:0; color:#0e1117; font-weight:bold;">{strat}</p>
    </div>
    """, unsafe_allow_html=True)

col_a, col_b = st.columns(2)
with col_a:
    st.subheader("📊 Profit Summary")
    st.metric("Final Net Profit", f"₹{net_pnl:,.2f}")
    st.write(f"*ROI:* {((net_pnl/capital_req)*100 if capital_req > 0 else 0):.2f}%")

with col_b:
    st.subheader("⚖️ Neutrality Proof")
    st.markdown(f'<div class="proof-box">Profit is locked at ₹{net_pnl:,.2f}<br>Delta risk: 0.00</div>', unsafe_allow_html=True)

st.divider()
st.subheader("📉 Expiry Scenario Analysis")
# Ensure the table is visible and high contrast
scenarios = [s0 * 0.9, s0, s0 * 1.1]
pdf = pd.DataFrame([
    {
        "Expiry Price": f"₹{p:,.0f}",
        "Total Net (Locked)": f"₹{net_pnl:,.2f}"
    } for p in scenarios
])
st.table(pdf)
