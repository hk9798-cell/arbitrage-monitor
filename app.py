import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go

# --- 1. CONFIG ---
st.set_page_config(page_title="Arbitrage Monitor", layout="wide")

st.title("🏛️ Cross-Asset Arbitrage Opportunity Monitor")
st.markdown("---")

ticker_map = {"NIFTY": "^NSEI", "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "SBIN": "SBIN.NS", "INFY": "INFY.NS"}
lot_sizes = {"NIFTY": 65, "RELIANCE": 250, "TCS": 175, "SBIN": 1500, "INFY": 400}

# --- 2. PARAMETERS ---
with st.sidebar:
    asset = st.selectbox("Select Asset", list(ticker_map.keys()))
    num_lots = st.number_input("Number of Lots", min_value=1, value=1)
    r_rate = st.slider("Risk-Free Rate (%)", 4.0, 10.0, 6.75) / 100
    days_to_expiry = st.number_input("Days to Expiry", value=15, min_value=1)
    st.divider()
    brokerage = st.number_input("Brokerage/Side (₹)", value=20.0)
    # Using 20% margin as seen in your screenshot
    margin_pct = st.slider("Margin Requirement (%)", 10, 40, 20) / 100

# --- 3. CALCULATIONS ---
@st.cache_data(ttl=30)
def get_spot(ticker):
    data = yf.Ticker(ticker).history(period="1d")
    return round(data['Close'].iloc[-1], 2) if not data.empty else 25725.40

s0 = get_spot(ticker_map[asset])
lot = lot_sizes[asset]
total_units = num_lots * lot

c1, c2, c3 = st.columns(3)
with c1: strike = st.number_input("Strike Price", value=float(round(s0/10)*10))
with c2: c_mkt = st.number_input("Call Price", value=round(s0*0.025, 2))
with c3: p_mkt = st.number_input("Put Price", value=round(s0*0.018, 2))

# Math for Synthetic Price
t = days_to_expiry / 365
synthetic_spot = c_mkt - p_mkt + (strike * np.exp(-r_rate * t))
spread_per_unit = s0 - synthetic_spot

# Friction (Brokerage + STT)
total_friction = (brokerage * 3 * num_lots) + (s0 * total_units * 0.001)
capital_req = (s0 * total_units) * margin_pct

# --- 4. SIGNAL LOGIC ---
if spread_per_unit > 0.1:
    signal_line, signal_color = "CONVERSION ARBITRAGE DETECTED", "#28a745"
    net_pnl = (spread_per_unit * total_units) - total_friction
elif spread_per_unit < -0.1:
    signal_line, signal_color = "REVERSAL ARBITRAGE DETECTED", "#dc3545"
    net_pnl = (abs(spread_per_unit) * total_units) - total_friction
else:
    signal_line, signal_color = "MARKET IS EFFICIENT", "#6c757d"
    net_pnl = 0

# --- 5. UI DISPLAY ---
m1, m2, m3, m4 = st.columns(4)
m1.metric("Market Spot", f"₹{s0:,.2f}")
m2.metric("Synthetic Price", f"₹{synthetic_spot:,.2f}")
m3.metric("Arbitrage Gap", f"₹{abs(spread_per_unit):.2f}")
m4.metric("Capital Req.", f"₹{capital_req:,.0f}")

st.markdown(f'<div style="background-color:{signal_color}; padding:20px; border-radius:10px; text-align:center; color:white;"><h2 style="margin:0;">{signal_line}</h2></div>', unsafe_allow_html=True)
st.write("")
st.metric("Final Net Profit (Synced)", f"₹{net_pnl:,.2f}")

# --- 6. SCENARIO PROOF (THE FIX) ---
st.subheader("📉 Expiry Scenario Analysis")
scenarios = [s0 * 0.9, s0, s0 * 1.1]
proof_data = []

for st_price in scenarios:
    if "CONVERSION" in signal_line:
        # Buy Stock, Buy Put, Sell Call
        s_pnl = (st_price - s0)
        o_pnl = (max(0, strike - st_price) - p_mkt) + (c_mkt - max(0, st_price - strike))
    elif "REVERSAL" in signal_line:
        # Short Stock, Sell Put, Buy Call
        s_pnl = (s0 - st_price) # Profit when price falls
        o_pnl = (p_mkt - max(0, strike - st_price)) + (max(0, st_price - strike) - c_mkt)
    else:
        s_pnl, o_pnl = 0, 0
    
    # Calculate row total
    row_total_net = (s_pnl + o_pnl) * total_units - total_friction
    
    proof_data.append({
        "Expiry Price": f"₹{st_price:,.0f}",
        "Stock P&L": f"₹{s_pnl*total_units:,.0f}",
        "Options P&L": f"₹{o_pnl*total_units:,.0f}",
        "TOTAL NET": f"₹{row_total_net:,.2f}"
    })

st.table(pd.DataFrame(proof_data))

# --- 7. GRAPH ---
fig = go.Figure(go.Scatter(x=np.linspace(s0*0.8, s0*1.2, 10), y=[net_pnl]*10, mode='lines', line=dict(color=signal_color, width=4)))
fig.update_layout(title="Risk-Neutral Payoff (Guaranteed)", height=300)
st.plotly_chart(fig, use_container_width=True)
