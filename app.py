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
    .strategy-text { font-weight: bold; font-size: 18px; margin-bottom: 5px; }
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
    days_to_expiry = st.number_input("Days to Expiry", value=15, min_value=1)
    st.divider()
    brokerage = st.number_input("Brokerage/Side (₹)", value=20.0)
    margin_pct = st.slider("Margin Requirement (%)", 10, 40, 20) / 100

# --- 3. DATA ENGINE ---
@st.cache_data(ttl=30)
def get_market_data(ticker):
    stock = yf.Ticker(ticker)
    spot = stock.history(period="1d")['Close'].iloc[-1]
    
    # Get the nearest expiry option chain
    try:
        expiry = stock.options[0]
        chain = stock.option_chain(expiry)
        return round(spot, 2), chain.calls, chain.puts
    except:
        return round(spot, 2), pd.DataFrame(), pd.DataFrame()

s0, calls_df, puts_df = get_market_data(ticker_map[asset])
lot = lot_sizes[asset]
total_units = num_lots * lot

# STRIKE SELECTION
c1, c2, c3 = st.columns(3)
with c1:
    # Set default strike to nearest ATM
    default_strike = float(round(s0/50)*50) if "NIFTY" in asset else float(round(s0/10)*10)
    strike = st.number_input("Strike Price", value=default_strike, step=50.0 if "NIFTY" in asset else 10.0)

# DYNAMIC CALL/PUT PRICE LOOKUP
with c2:
    current_c = 0.0
    if not calls_df.empty and strike in calls_df['strike'].values:
        current_c = calls_df[calls_df['strike'] == strike]['lastPrice'].values[0]
    c_mkt = st.number_input("Call Price", value=float(current_c))

with c3:
    current_p = 0.0
    if not puts_df.empty and strike in puts_df['strike'].values:
        current_p = puts_df[puts_df['strike'] == strike]['lastPrice'].values[0]
    p_mkt = st.number_input("Put Price", value=float(current_p))

# --- 4. CALCULATIONS ---
t = days_to_expiry / 365
pv_k = strike * np.exp(-r_rate * t)
synthetic_spot = c_mkt - p_mkt + pv_k
spread_per_unit = s0 - synthetic_spot
total_friction = (brokerage * 3 * num_lots) + (s0 * total_units * 0.001)
capital_req = (s0 * total_units) * margin_pct

if spread_per_unit > 0.1:
    signal_line, signal_color, strategy_desc = "CONVERSION ARBITRAGE DETECTED", "#28a745", "Buy Spot, Buy Put, Sell Call"
    net_pnl = (spread_per_unit * total_units) - total_friction
elif spread_per_unit < -0.1:
    signal_line, signal_color, strategy_desc = "REVERSAL ARBITRAGE DETECTED", "#dc3545", "Short Spot, Sell Put, Buy Call"
    net_pnl = (abs(spread_per_unit) * total_units) - total_friction
else:
    signal_line, signal_color, net_pnl, strategy_desc = "MARKET IS EFFICIENT", "#6c757d", 0, "No Action"

# Metrics & UI
m1, m2, m3, m4 = st.columns(4)
m1.metric("Market Spot", f"₹{s0:,.2f}")
m2.metric("Synthetic Price", f"₹{synthetic_spot:,.2f}")
m3.metric("Arbitrage Gap", f"₹{abs(spread_per_unit):.2f}")
m4.metric("Capital Req.", f"₹{capital_req:,.0f}")

st.markdown(f'<div style="background-color:{signal_color}; padding:15px; border-radius:10px; text-align:center; color:white;"><h2 style="margin:0;">{signal_line}</h2></div>', unsafe_allow_html=True)

# Side-by-Side Proof and Graph
st.write("")
col_proof, col_graph = st.columns([1, 1.2])
with col_proof:
    st.subheader("📊 Execution Proof")
    st.markdown(f'<div class="strategy-text">Strategy: {strategy_desc}</div>', unsafe_allow_html=True)
    st.latex(r"P = Units \times [ (S_{T} - S_{0}) + (K - S_{T})^{+} - (S_{T} - K)^{+} + (C - P) ]")
    st.metric("Final Net Profit", f"₹{net_pnl:,.2f}")
    st.write(f"Profit locked for {total_units} units.")

with col_graph:
    prices = np.linspace(s0*0.8, s0*1.2, 20)
    fig = go.Figure(go.Scatter(x=prices, y=[net_pnl]*20, mode='lines', line=dict(color=signal_color, width=4)))
    fig.update_layout(title="Risk-Neutral Payoff", height=280, margin=dict(t=30, b=0, l=0, r=0))
    st.plotly_chart(fig, use_container_width=True)

# Scenario Table
st.divider()
st.subheader("📉 Expiry Scenario Analysis")
scenarios = [s0 * 0.9, s0, s0 * 1.1]
proof_data = [{"Price at Expiry": f"₹{p:,.0f}", "Lot Size": lot, "Total Units": total_units, "TOTAL NET": f"₹{net_pnl:,.2f}"} for p in scenarios]
st.table(pd.DataFrame(proof_data))
