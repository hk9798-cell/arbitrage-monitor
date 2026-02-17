import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go

# --- 1. CONFIG & STYLING ---
st.set_page_config(page_title="Arbitrage Monitor", layout="wide")
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    div[data-testid="stMetricValue"] { font-size: 26px; color: #007bff; font-weight: bold; }
    .stTable { border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
    .calc-box { background-color: #ffffff; padding: 15px; border-left: 5px solid #007bff; border-radius: 5px; margin-bottom: 10px; font-family: monospace; }
    </style>
    """, unsafe_allow_html=True)

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
with c1: strike = st.number_input("Strike Price", value=float(round(s0/10)*10))
with c2: c_mkt = st.number_input("Call Price", value=round(s0*0.025, 2))
with c3: p_mkt = st.number_input("Put Price", value=round(s0*0.018, 2))

t = days_to_expiry / 365
synthetic_spot = c_mkt - p_mkt + (strike * np.exp(-r_rate * t))
spread_per_unit = s0 - synthetic_spot

# Unified Friction Logic
total_friction = (brokerage * 3 * num_lots) + (s0 * total_units * 0.001)
capital_req = (s0 * total_units) * margin_pct

# --- 4. SIGNAL & PROFIT ---
if spread_per_unit > 0.1:
    signal_line, signal_color = "CONVERSION ARBITRAGE DETECTED", "#28a745"
    net_pnl = (spread_per_unit * total_units) - total_friction
elif spread_per_unit < -0.1:
    signal_line, signal_color = "REVERSAL ARBITRAGE DETECTED", "#dc3545"
    net_pnl = (abs(spread_per_unit) * total_units) - total_friction
else:
    signal_line, signal_color = "MARKET IS EFFICIENT", "#6c757d"
    net_pnl = 0

st.divider()
m1, m2, m3, m4 = st.columns(4)
m1.metric("Market Spot", f"₹{s0:,.2f}")
m2.metric("Synthetic Price", f"₹{synthetic_spot:,.2f}")
m3.metric("Arbitrage Gap", f"₹{abs(spread_per_unit):.2f}")
m4.metric("Capital Req.", f"₹{capital_req:,.0f}")

col_left, col_right = st.columns([1, 1.2])

with col_left:
    st.markdown(f'<div style="background-color:{signal_color}; padding:20px; border-radius:10px; text-align:center; color:white;"><h2 style="margin:0;">{signal_line}</h2></div>', unsafe_allow_html=True)
    st.write("")
    st.metric("Final Net Profit (Synced)", f"₹{net_pnl:,.2f}")
    
    st.subheader("🧮 Calculation Breakdown")
    st.markdown(f"""<div class="calc-box">
        Spread/Unit: ₹{abs(spread_per_unit):.2f}<br>
        Gross Profit: ₹{(abs(spread_per_unit)*total_units):,.2f}<br>
        Total Friction: ₹{total_friction:,.2f}<br>
        <b>Net Profit: ₹{net_pnl:,.2f}</b></div>""", unsafe_allow_html=True)

with col_right:
    st.subheader("📊 Payoff Proof & Formula")
    st.latex(r"Profit = Units \times [ (S_{T} - S_{0}) + (K - S_{T})^{+} - (S_{T} - K)^{+} + (C - P) ]")
    prices = np.linspace(s0*0.9, s0*1.1, 20)
    fig = go.Figure(go.Scatter(x=prices, y=[net_pnl]*20, mode='lines', line=dict(color=signal_color, width=4)))
    fig.update_layout(title="Risk-Neutral Locked Profit", height=300, template="plotly_white")
    st.plotly_chart(fig, use_container_width=True)

st.subheader("📉 Expiry Scenario Analysis")
scenarios = [s0 * 0.9, s0, s0 * 1.1]
proof_data = []
for st_price in scenarios:
    if "CONVERSION" in signal_line:
        s_pnl = (st_price - s0); o_pnl = (max(0, strike - st_price) - p_mkt) + (c_mkt - max(0, st_price - strike))
    else: # Reversal
        s_pnl = (s0 - st_price); o_pnl = (p_mkt - max(0, strike - st_price)) + (max(0, st_price - strike) - c_mkt)
    
    # Crucial Fix: Applying the EXACT same total friction used in the main calculation
    total_net_scenario = (s_pnl + o_pnl) * total_units - total_friction
    
    proof_data.append({"Expiry Price": f"₹{st_price:,.0f}", "Stock P&L": f"₹{s_pnl*total_units:,.0f}", "Options P&L": f"₹{o_pnl*total_units:,.0f}", "TOTAL NET": f"₹{total_net_scenario:,.2f}"})
st.table(pd.DataFrame(proof_data))
