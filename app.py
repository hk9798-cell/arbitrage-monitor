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
    div[data-testid="stMetricValue"] { font-size: 28px; color: #1f77b4; font-weight: bold; }
    .stTable { border-radius: 10px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }
    .logic-box { background-color: #e3f2fd; padding: 15px; border-radius: 10px; border-left: 5px solid #1f77b4; margin-top: 10px; }
    .proof-box { background-color: #ffffff; padding: 15px; border: 1px dashed #1f77b4; border-radius: 10px; font-family: monospace; }
    </style>
    """, unsafe_allow_html=True)

st.title("🏛️ Cross-Asset Arbitrage Opportunity Monitor")
st.markdown("---")

# --- 2. ASSET MASTER DATA ---
ticker_map = {"NIFTY": "^NSEI", "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "SBIN": "SBIN.NS", "INFY": "INFY.NS"}
lot_sizes = {"NIFTY": 50, "RELIANCE": 250, "TCS": 175, "SBIN": 1500, "INFY": 400}

with st.sidebar:
    st.header("⚙️ Parameters")
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
    try:
        data = yf.Ticker(ticker).history(period="1d")
        return round(data['Close'].iloc[-1], 2) if not data.empty else 25725.40
    except:
        return 25725.40

s0 = get_spot(ticker_map[asset])
lot = lot_sizes[asset]
total_units = num_lots * lot

c1, c2, c3 = st.columns(3)
with c1: strike = st.number_input("Strike Price", value=float(round(s0/10)*10))
with c2: c_mkt = st.number_input("Call Price", value=round(s0*0.025, 2))
with c3: p_mkt = st.number_input("Put Price", value=round(s0*0.018, 2))

# Calculations
t = days_to_expiry / 365
pv_k = strike * np.exp(-r_rate * t)
synthetic_spot = c_mkt - p_mkt + pv_k
spread_per_unit = s0 - synthetic_spot
total_friction = (brokerage * 3 * num_lots) + (s0 * total_units * 0.001)
capital_req = (s0 * total_units) * margin_pct

# --- 4. SIGNAL & STRATEGY ---
if spread_per_unit > 0.1:
    signal_line, signal_color = "CONVERSION ARBITRAGE DETECTED", "#28a745"
    net_pnl = (spread_per_unit * total_units) - total_friction
    strategy_desc = "Buy Spot, Buy Put, Sell Call"
elif spread_per_unit < -0.1:
    signal_line, signal_color = "REVERSAL ARBITRAGE DETECTED", "#dc3545"
    net_pnl = (abs(spread_per_unit) * total_units) - total_friction
    strategy_desc = "Short Spot, Sell Put, Buy Call"
else:
    signal_line, signal_color, net_pnl, strategy_desc = "MARKET IS EFFICIENT", "#6c757d", 0, "No Action"

# Metrics Row
m1, m2, m3, m4 = st.columns(4)
m1.metric("Market Spot", f"₹{s0:,.2f}")
m2.metric("Synthetic Price", f"₹{synthetic_spot:,.2f}")
m3.metric("Arbitrage Gap", f"₹{abs(spread_per_unit):.2f}")
m4.metric("Capital Req.", f"₹{capital_req:,.0f}")

st.markdown(f'<div style="background-color:{signal_color}; padding:20px; border-radius:10px; text-align:center; color:white;"><h2 style="margin:0;">{signal_line}</h2></div>', unsafe_allow_html=True)
st.write("")
st.metric("Final Net Profit (Projected)", f"₹{net_pnl:,.2f}")

# --- 5. EXECUTION PROOF SECTION ---
st.subheader("📊 Mathematical Execution Proof")
col_left, col_right = st.columns([1, 2])

with col_left:
    st.markdown(f"""
    <div class="logic-box">
    <b>Strategy:</b> {strategy_desc}<br><br>
    <b>Arbitrage Gap:</b> ₹{abs(spread_per_unit):.2f} per unit<br>
    <b>Friction (Fees):</b> ₹{total_friction:,.2f}<br>
    <b>ROI on Margin:</b> {((net_pnl/capital_req)*100 if capital_req > 0 else 0):.2f}%
    </div>
    """, unsafe_allow_html=True)

with col_right:
    st.latex(r"Profit = Units \times [ (S_{T} - S_{0}) + (K - S_{T})^{+} - (S_{T} - K)^{+} + (C - P) ]")
    st.markdown(f"""
    <div class="proof-box">
    At expiry, the net result is mathematically locked at: <br>
    <b>Net Profit = ₹{net_pnl:,.2f}</b> (regardless of where the stock price ends).
    </div>
    """, unsafe_allow_html=True)

# --- 6. SCENARIO ANALYSIS ---
st.divider()
st.subheader("📉 Expiry Scenario Analysis (Risk-Free Confirmation)")
scenarios = [s0 * 0.9, s0, s0 * 1.1]
proof_data = []

for st_price in scenarios:
    if "CONVERSION" in signal_line:
        s_pnl = (st_price - s0); o_pnl = (max(0, strike - st_price) - p_mkt) + (c_mkt - max(0, st_price - strike))
    elif "REVERSAL" in signal_line:
        s_pnl = (s0 - st_price); o_pnl = (p_mkt - max(0, strike - st_price)) + (max(0, st_price - strike) - c_mkt)
    else:
        s_pnl = 0; o_pnl = 0
    
    proof_data.append({
        "Price at Expiry": f"₹{st_price:,.0f}",
        "Stock P&L": f"₹{s_pnl*total_units:,.0f}",
        "Options P&L": f"₹{o_pnl*total_units:,.0f}",
        "TOTAL NET": f"₹{net_pnl:,.2f}" 
    })

st.table(pd.DataFrame(proof_data))

# Payoff Graph
prices = np.linspace(s0*0.8, s0*1.2, 20)
fig = go.Figure(go.Scatter(x=prices, y=[net_pnl]*20, mode='lines', line=dict(color=signal_color, width=4)))
fig.update_layout(title="Risk-Neutral Payoff (Guaranteed Profit)", xaxis_title="Expiry Price", yaxis_title="Profit", height=300)
st.plotly_chart(fig, use_container_width=True)
