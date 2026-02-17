import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# --- 1. CONFIG & CUSTOM STYLING ---
st.set_page_config(page_title="Arbitrage Monitor", layout="wide")

# Fixed CSS styling for better visual appeal
st.markdown("""
    <style>
    .main {
        background-color: #f0f2f6;
    }
    div[data-testid="stMetricValue"] {
        font-size: 24px;
        color: #1f77b4;
    }
    .stTable {
        border-radius: 10px;
        overflow: hidden;
    }
    </style>
    """, unsafe_allow_html=True)

# Updated Header
st.title("🏛️ Cross-Asset Arbitrage Opportunity Monitor")
st.markdown("---")

ticker_map = {
    "NIFTY": "^NSEI", "RELIANCE": "RELIANCE.NS", 
    "TCS": "TCS.NS", "SBIN": "SBIN.NS", "INFY": "INFY.NS"
}
lot_sizes = {"NIFTY": 65, "RELIANCE": 250, "TCS": 175, "SBIN": 1500, "INFY": 400}

# --- 2. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Strategy Parameters")
    asset = st.selectbox("Select Asset", list(ticker_map.keys()))
    num_lots = st.number_input("Number of Lots", min_value=1, value=1)
    r_rate = st.slider("Risk-Free Rate (%)", 4.0, 10.0, 6.75) / 100
    days_to_expiry = st.number_input("Days to Expiry", value=15, min_value=1)
    
    st.divider()
    brokerage = st.number_input("Brokerage/Side (₹)", value=20.0)
    margin_pct = st.slider("Margin Requirement (%)", 10, 40, 20) / 100

# --- 3. DATA ENGINE ---
@st.cache_data(ttl=30)
def get_spot(ticker):
    data = yf.Ticker(ticker).history(period="1d")
    return round(data['Close'].iloc[-1], 2) if not data.empty else 25000.0

s0 = get_spot(ticker_map[asset])
lot = lot_sizes[asset]
total_units = num_lots * lot

# Manual inputs for Option prices
c1, c2, c3 = st.columns(3)
with c1: strike = st.number_input("Strike Price", value=float(round(s0/10)*10))
with c2: c_mkt = st.number_input("Call Market Price", value=round(s0*0.025, 2))
with c3: p_mkt = st.number_input("Put Market Price", value=round(s0*0.018, 2))

# Calculations
t = days_to_expiry / 365
synthetic_spot = c_mkt - p_mkt + (strike * np.exp(-r_rate * t))
spread = s0 - synthetic_spot
total_costs = (brokerage * 3 * num_lots) + (s0 * total_units * 0.001)
capital_req = (s0 * total_units) * margin_pct

# --- 4. TOP METRICS (Visible Spot Price) ---
m1, m2, m3, m4 = st.columns(4)
m1.metric("Actual Market Spot", f"₹{s0:,.2f}")
m2.metric("Synthetic Fair Price", f"₹{synthetic_spot:,.2f}")
m3.metric("Arbitrage Gap", f"₹{abs(spread):.2f}")
m4.metric("Capital Required", f"₹{capital_req:,.0f}")

# --- 5. EXECUTION & PROOF SECTION ---
st.markdown("---")
col_left, col_right = st.columns([1, 1.2])

# Signal Logic with Dynamic Banner
if spread > 0.5:
    signal_text = "CONVERSION ARBITRAGE DETECTED"
    signal_color = "#28a745" # Green
    net_pnl = (spread * total_units) - total_costs
elif spread < -0.5:
    signal_text = "REVERSAL ARBITRAGE DETECTED"
    signal_color = "#dc3545" # Red
    net_pnl = (abs(spread) * total_units) - total_costs
else:
    signal_text = "MARKET IS EFFICIENT"
    signal_color = "#6c757d" # Gray
    net_pnl = 0

with col_left:
    # High-Visibility Signal Banner
    st.markdown(f"""
        <div style="background-color:{signal_color}; padding:20px; border-radius:10px; text-align:center;">
            <h2 style="color:white; margin:0; font-family:sans-serif;">{signal_text}</h2>
        </div>
        """, unsafe_allow_html=True)
    
    st.write("")
    st.metric(f"Projected Net Profit ({num_lots} Lots)", f"₹{net_pnl:,.2f}")
    
    # Strategy Actions
    actions = []
    if "CONVERSION" in signal_text:
        actions = [
            {"Action": "BUY", "Item": f"{asset} Underlying", "Price": s0},
            {"Action": "BUY", "Item": f"{strike} Put", "Price": p_mkt},
            {"Action": "SELL", "Item": f"{strike} Call", "Price": c_mkt}
        ]
    elif "REVERSAL" in signal_text:
        actions = [
            {"Action": "SELL/SHORT", "Item": f"{asset} Underlying", "Price": s0},
            {"Action": "SELL", "Item": f"{strike} Put", "Price": p_mkt},
            {"Action": "BUY", "Item": f"{strike} Call", "Price": c_mkt}
        ]

    if actions:
        st.table(pd.DataFrame(actions))
        st.download_button("📥 Download Trade Sheet", pd.DataFrame(actions).to_csv().encode('utf-8'), "trade.csv")

with col_right:
    st.subheader("📊 Mathematical Execution Proof")
    
    # Professional Formula Rendering
    st.markdown("*Core Proof Formula:*")
    st.latex(r"Profit = Units \times [ (S_{T} - S_{0}) + (K - S_{T})^{+} - (S_{T} - K)^{+} + (C - P) ]")
    
    # Proof Table (Scenario Analysis)
    scenarios = [s0 * 0.9, s0, s0 * 1.1]
    proof_data = []
    for st_price in scenarios:
        if "CONVERSION" in signal_text:
            s_pnl = (st_price - s0)
            o_pnl = (max(0, strike - st_price) - p_mkt) + (c_mkt - max(0, st_price - strike))
        elif "REVERSAL" in signal_text:
            s_pnl = (s0 - st_price)
            o_pnl = (p_mkt - max(0, strike - st_price)) + (max(0, st_price - strike) - c_mkt)
        else: s_pnl, o_pnl = 0, 0
            
        total_pnl = (s_pnl + o_pnl) * total_units - total_costs
        proof_data.append({
            "Expiry Price": f"₹{st_price:,.0f}",
            "Stock P&L": f"₹{s_pnl*total_units:,.0f}",
            "Options P&L": f"₹{o_pnl*total_units:,.0f}",
            "TOTAL NET": f"₹{total_pnl:,.2f}"
        })
    st.table(pd.DataFrame(proof_data))
    st.caption("Proof: TOTAL NET remains constant across all expiry price scenarios.")

# Chart for visual appeal
prices = np.linspace(s0*0.8, s0*1.2, 20)
fig = go.Figure(go.Scatter(x=prices, y=[net_pnl
