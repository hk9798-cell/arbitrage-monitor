import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# --- 1. CONFIG & UI STYLING ---
st.set_page_config(page_title="Arbitrage Monitor", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }
    
    /* MAKING LABELS BOLD */
    label[data-testid="stWidgetLabel"] p {
        font-weight: bold !important;
        font-size: 16px !important;
    }
    
    div[data-testid="stMetricLabel"] p { 
        font-weight: bold !important; 
        font-size: 16px !important; 
    }
    
    div[data-testid="stMetricValue"] { font-size: 28px; color: #1f77b4; font-weight: bold; }
    .stTable { border-radius: 10px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.1); }
    
    .strategy-text {
        font-weight: bold;
        font-size: 18px;
        margin-bottom: 5px;
    }
    </style>
    """, unsafe_allow_html=True)

st.title("🏛️ Cross-Asset Arbitrage Opportunity Monitor")

# --- 2. ASSET MASTER DATA ---
ticker_map = {"NIFTY": "^NSEI", "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "SBIN": "SBIN.NS", "INFY": "INFY.NS"}
lot_sizes = {"NIFTY": 65, "RELIANCE": 250, "TCS": 175, "SBIN": 1500, "INFY": 400}

with st.sidebar:
    st.header("⚙️ Parameters")
    asset = st.selectbox("Select Asset", list(ticker_map.keys()))
    num_lots = st.number_input("Number of Lots", min_value=1, value=1)
    r_rate = st.slider("Risk-Free Rate (%)", 4.0, 10.0, 6.75) / 100
    st.divider()
    brokerage = st.number_input("Brokerage/Side (₹)", value=20.0)
    margin_pct = st.slider("Margin Requirement (%)", 10, 40, 20) / 100
    
    if st.button("🔄 Refresh Live Prices"):
        st.cache_data.clear()

# --- 3. DYNAMIC DATA ENGINE ---
@st.cache_data(ttl=60)
def fetch_live_market_data(ticker_symbol):
    # Safe Defaults
    s, k, c, p, d = 25000.0, 25000.0, 400.0, 350.0, 15
    try:
        stock = yf.Ticker(ticker_symbol)
        history = stock.history(period="1d")
        if not history.empty:
            s = history['Close'].iloc[-1]
            
        expirations = stock.options
        if expirations:
            # Fetching the nearest expiry option chain
            chain = stock.option_chain(expirations[0])
            calls, puts = chain.calls, chain.puts
            
            # Find the strike closest to current market price (ATM)
            atm_idx = (calls['strike'] - s).abs().idxmin()
            k = calls.loc[atm_idx, 'strike']
            c = calls.loc[atm_idx, 'lastPrice']
            p = puts.loc[atm_idx, 'lastPrice']
            
            # Calculate days to expiry dynamically
            d1 = datetime.strptime(expirations[0], '%Y-%m-%d')
            d = max((d1 - datetime.now()).days, 1)
            
        return float(s), float(k), float(c), float(p), int(d)
    except:
        return s, k, c, p, d

# Fetching Actual Market Values
s0, live_k, live_c, live_p, dte = fetch_live_market_data(ticker_map[asset])
lot = lot_sizes[asset]
total_units = num_lots * lot

# Inputs (Pre-filled with Live Market Data)
c1, c2, c3 = st.columns(3)
with c1: strike = st.number_input("Strike Price", value=live_k)
with c2: c_mkt = st.number_input("Call Price", value=live_c)
with c3: p_mkt = st.number_input("Put Price", value=live_p)

# Calculations
t = dte / 365
pv_k = strike * np.exp(-r_rate * t)
synthetic_spot = c_mkt - p_mkt + pv_k
spread_per_unit = s0 - synthetic_spot
total_friction = (brokerage * 3 * num_lots) + (s0 * total_units * 0.001)
capital_req = (s0 * total_units) * margin_pct

# --- 4. SIGNAL & METRICS ---
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

m1, m2, m3, m4 = st.columns(4)
m1.metric("Market Spot", f"₹{s0:,.2f}")
m2.metric("Synthetic Price", f"₹{synthetic_spot:,.2f}")
m3.metric("Arbitrage Gap", f"₹{abs(spread_per_unit):.2f}")
m4.metric("Days to Expiry", f"{dte} Days")

st.markdown(f'<div style="background-color:{signal_color}; padding:15px; border-radius:10px; text-align:center; color:white;"><h2 style="margin:0;">{signal_line}</h2></div>', unsafe_allow_html=True)

# --- 5. HIGH-VISIBILITY SECTION ---
st.write("")
col_proof, col_graph = st.columns([1, 1.2])

with col_proof:
    st.subheader("📊 Execution Proof")
    st.markdown(f'<div class="strategy-text">Strategy: {strategy_desc}</div>', unsafe_allow_html=True)
    st.latex(r"P = Units \times [ (S_{T} - S_{0}) + (K - S_{T})^{+} - (S_{T} - K)^{+} + (C - P) ]")
    st.metric("Final Net Profit", f"₹{net_pnl:,.2f}")
    st.write(f"Profit locked for {total_units} units (After ₹{total_friction:,.2f} fees).")

with col_graph:
    prices = np.linspace(s0*0.8, s0*1.2, 20)
    fig = go.Figure(go.Scatter(x=prices, y=[net_pnl]*20, mode='lines', line=dict(color=signal_color, width=4)))
    fig.update_layout(title="Risk-Neutral Payoff", xaxis_title="Expiry Price", yaxis_title="Profit", height=280, margin=dict(t=30, b=0, l=0, r=0))
    st.plotly_chart(fig, use_container_width=True)

# --- 6. SCENARIO ANALYSIS (WITH LOT DETAILS) ---
st.divider()
st.subheader("📉 Expiry Scenario Analysis (Detailed)")
scenarios = [s0 * 0.9, s0, s0 * 1.1]
proof_data = []

for st_price in scenarios:
    if "CONVERSION" in signal_line:
        s_pnl = (st_price - s0); o_pnl = (max(0, strike - st_price) - p_mkt) + (c_mkt - max(0, st_price - strike))
    else:
        s_pnl = (s0 - st_price); o_pnl = (p_mkt - max(0, strike - st_price)) + (max(0, st_price - strike) - c_mkt)
    
    proof_data.append({
        "Price at Expiry": f"₹{st_price:,.0f}",
        "Lot Size": lot,
        "Total Units": total_units,
        "Stock P&L": f"₹{s_pnl*total_units:,.0f}",
        "Options P&L": f"₹{o_pnl*total_units:,.0f}",
        "TOTAL NET": f"₹{net_pnl:,.2f}" 
    })

st.table(pd.DataFrame(proof_data))
