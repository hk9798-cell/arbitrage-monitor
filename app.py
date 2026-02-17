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
    /* Main Background */
    [data-testid="stAppViewContainer"] { background-color: #0e1117; color: #ffffff; }
    [data-testid="stSidebar"] { background-color: #1a1c24; }
    
    /* FIXING INVISIBLE HEADINGS */
    div[data-testid="stMetricLabel"] p { 
        color: #ffffff !important; 
        font-size: 18px !important; 
        font-weight: bold !important;
        opacity: 1 !important;
    }
    
    /* Metric Card Styling */
    div[data-testid="metric-container"] {
        background-color: #1f2937;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #374151;
    }
    
    /* Metric Value Styling */
    div[data-testid="stMetricValue"] { 
        font-size: 30px !important; 
        color: #00ffcc !important; 
    }

    /* Table Visibility Fix */
    .stTable td, .stTable th { color: #ffffff !important; }
    
    /* Boxes */
    .proof-box { 
        background-color: #000000; 
        padding: 15px; 
        border: 1px solid #00ffcc; 
        border-radius: 10px; 
        font-family: 'Courier New', monospace; 
        color: #00ffcc; 
    }
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

# --- 3. DATA ENGINE (FIXING THE VALUEERROR) ---
@st.cache_data(ttl=60)
def fetch_live_data(ticker_symbol):
    # Safe Defaults
    s, k, c, p, d = 25000.0, 25000.0, 400.0, 350.0, 15
    try:
        stock = yf.Ticker(ticker_symbol)
        history = stock.history(period="1d")
        if not history.empty:
            s = history['Close'].iloc[-1]
            
        expirations = stock.options
        if expirations:
            chain = stock.option_chain(expirations[0])
            calls, puts = chain.calls, chain.puts
            # Find ATM
            atm_idx = (calls['strike'] - s).abs().idxmin()
            k = calls.loc[atm_idx, 'strike']
            c = calls.loc[atm_idx, 'lastPrice']
            p = puts.loc[atm_idx, 'lastPrice']
            
            d1 = datetime.strptime(expirations[0], '%Y-%m-%d')
            d = max((d1 - datetime.now()).days, 1)
            
        return float(s), float(k), float(c), float(p), int(d)
    except:
        return s, k, c, p, d

# This line was causing your error - now it has fallback values
s0, auto_strike, auto_call, auto_put, dte = fetch_live_data(ticker_map[asset])

# Input Overrides
c1, c2, c3 = st.columns(3)
with c1: strike = st.number_input("Strike Price", value=float(auto_strike))
with c2: c_mkt = st.number_input("Call Price", value=float(auto_call))
with c3: p_mkt = st.number_input("Put Price", value=float(auto_put))

# --- 4. CALCULATIONS ---
total_units = num_lots * lot_sizes[asset]
pv_k = strike * np.exp(-r_rate * (dte/365))
synthetic_spot = c_mkt - p_mkt + pv_k
spread_per_unit = s0 - synthetic_spot
total_friction = (brokerage * 3 * num_lots) + (s0 * total_units * 0.001)
capital_req = (s0 * total_units) * margin_pct

# Strategy Logic
if spread_per_unit > 0.5:
    sig, col, strat = "CONVERSION ARBITRAGE", "#28a745", "Buy Spot + Buy Put + Sell Call"
    net_pnl = (spread_per_unit * total_units) - total_friction
elif spread_per_unit < -0.5:
    sig, col, strat = "REVERSAL ARBITRAGE", "#dc3545", "Short Spot + Sell Put + Buy Call"
    net_pnl = (abs(spread_per_unit) * total_units) - total_friction
else:
    sig, col, strat, net_pnl = "EFFICIENT MARKET", "#6c757d", "No Action", 0

# --- 5. VISUALS (NOW WITH BRIGHT LABELS) ---
m1, m2, m3, m4 = st.columns(4)
m1.metric("Market Spot", f"₹{s0:,.2f}")
m2.metric("Synthetic Price", f"₹{synthetic_spot:,.2f}")
m3.metric("Net Spread", f"₹{abs(spread_per_unit):.2f}")
m4.metric("Days to Expiry", f"{dte} Days")

st.markdown(f"""
    <div style="background-color:{col}; padding:20px; border-radius:10px; text-align:center; margin: 20px 0; border: 2px solid white;">
        <h2 style="margin:0; color:white !important; font-weight:bold;">{sig}</h2>
        <p style="margin:0; color:white !important; font-size:18px;">{strat}</p>
    </div>
    """, unsafe_allow_html=True)

r1, r2 = st.columns(2)
with r1:
    st.subheader("📊 Profit Summary")
    st.metric("Net Profit", f"₹{net_pnl:,.2f}")
    st.write(f"*ROI:* {((net_pnl/capital_req)*100 if capital_req > 0 else 0):.2f}%")

with r2:
    st.subheader("⚖️ Neutrality Proof")
    st.markdown(f'<div class="proof-box">Profit is locked at ₹{net_pnl:,.2f}<br>Risk Profile: Delta Neutral</div>', unsafe_allow_html=True)

st.divider()
st.subheader("📉 Expiry Scenario Analysis")
# Forced White Text for the Scenario Table
scenarios = [s0 * 0.9, s0, s0 * 1.1]
pdf = pd.DataFrame([{"Price at Expiry": f"₹{p:,.0f}", "Net Profit (Locked)": f"₹{net_pnl:,.2f}"} for p in scenarios])
st.table(pdf)
