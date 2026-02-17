import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# --- 1. CONFIG & STYLING ---
st.set_page_config(page_title="Arbitrage Execution Monitor", layout="wide")
st.title("🏛️ Financial Engineering: Execution & Proof Dashboard")

ticker_map = {
    "NIFTY": "^NSEI", "RELIANCE": "RELIANCE.NS", 
    "TCS": "TCS.NS", "SBIN": "SBIN.NS", "INFY": "INFY.NS"
}
lot_sizes = {"NIFTY": 65, "RELIANCE": 250, "TCS": 175, "SBIN": 1500, "INFY": 400}

# --- 2. SIDEBAR ---
with st.sidebar:
    st.header("⚙️ Execution Parameters")
    asset = st.selectbox("Select Asset", list(ticker_map.keys()))
    num_lots = st.number_input("Number of Lots", min_value=1, value=1)
    r_rate = st.slider("Risk-Free Rate (%)", 4.0, 10.0, 6.75) / 100
    days_to_expiry = st.number_input("Days to Expiry", value=15, min_value=1)
    
    st.divider()
    brokerage = st.number_input("Brokerage/Side (₹)", value=20.0)
    margin_pct = st.slider("Margin Requirement (%)", 10, 40, 20) / 100

# --- 3. CALCULATIONS ---
@st.cache_data(ttl=30)
def get_spot(ticker):
    data = yf.Ticker(ticker).history(period="1d")
    return round(data['Close'].iloc[-1], 2) if not data.empty else 2500.0

s0 = get_spot(ticker_map[asset])
lot = lot_sizes[asset]
total_units = num_lots * lot

c1, c2, c3 = st.columns(3)
strike = c1.number_input("Strike Price", value=float(round(s0/10)*10))
c_mkt = c2.number_input("Call Price", value=round(s0*0.025, 2))
p_mkt = c3.number_input("Put Price", value=round(s0*0.018, 2))

# Parity Math
t = days_to_expiry / 365
synthetic_spot = c_mkt - p_mkt + (strike * np.exp(-r_rate * t))
spread = s0 - synthetic_spot
total_costs = (brokerage * 3 * num_lots) + (s0 * total_units * 0.001) # Brokerage + STT
capital_req = (s0 * total_units) * margin_pct

# --- 4. STRATEGY & SIGNAL ---
st.divider()
col_left, col_right = st.columns([1, 1.2])

if spread > 1.0:
    signal, color = "CONVERSION", "green"
    net_pnl_total = (spread * total_units) - total_costs
elif spread < -1.0:
    signal, color = "REVERSAL", "red"
    net_pnl_total = (abs(spread) * total_units) - total_costs
else:
    signal, color = "NEUTRAL", "gray"
    net_pnl_total = 0

with col_left:
    st.subheader(f"🛠️ Execution Plan: :{color}[{signal}]")
    st.metric("Total Capital Required", f"₹{capital_req:,.0f}")
    st.metric("Net Profit ({num_lots} Lots)", f"₹{net_pnl_total:,.2f}")
    
    # Table for CSV Download
    actions = []
    if signal == "CONVERSION":
        actions = [
            {"Action": "BUY", "Item": "Underlying", "Price": s0},
            {"Action": "BUY", "Item": "Put Option", "Price": p_mkt},
            {"Action": "SELL", "Item": "Call Option", "Price": c_mkt}
        ]
    elif signal == "REVERSAL":
        actions = [
            {"Action": "SELL/SHORT", "Item": "Underlying", "Price": s0},
            {"Action": "SELL", "Item": "Put Option", "Price": p_mkt},
            {"Action": "BUY", "Item": "Call Option", "Price": c_mkt}
        ]
    
    if actions:
        df_exec = pd.DataFrame(actions)
        df_exec['Total Qty'] = total_units
        st.table(df_exec)
        st.download_button("📥 Download Trade Report", df_exec.to_csv().encode('utf-8'), "trade_report.csv")

with col_right:
    st.subheader("📊 The Proof: Payoff Scenarios")
    
    # Calculation Logic for Proof Table
    scenarios = [s0 * 0.9, s0, s0 * 1.1] # -10%, ATM, +10%
    proof_rows = []
    
    for st_price in scenarios:
        if signal == "CONVERSION":
            stock_gain = (st_price - s0)
            opt_gain = (max(0, strike - st_price) - p_mkt) + (c_mkt - max(0, st_price - strike))
        elif signal == "REVERSAL":
            stock_gain = (s0 - st_price)
            opt_gain = (p_mkt - max(0, strike - st_price)) + (max(0, st_price - strike) - c_mkt)
        else:
            stock_gain, opt_gain = 0, 0
            
        final_pnl = (stock_gain + opt_gain) * total_units - total_costs
        proof_rows.append({
            "Price at Expiry": f"₹{st_price:,.0f}",
            "Stock P&L": f"₹{stock_gain * total_units:,.0f}",
            "Options P&L": f"₹{opt_gain * total_units:,.0f}",
            "NET PROFIT": f"₹{final_pnl:,.2f}"
        })

    st.table(pd.DataFrame(proof_rows))
    st.info("💡 Notice: The NET PROFIT remains constant regardless of the Price at Expiry.")

# Plotly Visual
prices = np.linspace(s0*0.85, s0*1.15, 20)
pnl_curve = [net_pnl_total for _ in prices]
fig = go.Figure(go.Scatter(x=prices, y=pnl_curve, name="Locked Profit", line=dict(color='gold', width=4)))
fig.update_layout(title="Arbitrage Payoff (Risk-Neutral)", height=300, margin=dict(l=0,r=0,b=0,t=40))
st.plotly_chart(fig, use_container_width=True)
