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

# --- 3. DYNAMIC DATA ENGINE ---
@st.cache_data(ttl=30)
def get_market_data(ticker):
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="1d")
        spot = hist['Close'].iloc[-1] if not hist.empty else 25725.40
        
        if stock.options:
            expiry = stock.options[0] # Fetches nearest actual expiry
            chain = stock.option_chain(expiry)
            return round(spot, 2), chain.calls, chain.puts, expiry
        return round(spot, 2), pd.DataFrame(), pd.DataFrame(), "N/A"
    except:
        return 25725.40, pd.DataFrame(), pd.DataFrame(), "N/A"

s0, calls_df, puts_df, current_expiry = get_market_data(ticker_map[asset])
lot = lot_sizes[asset]
total_units = num_lots * lot

# STRIKE SELECTION
c1, c2, c3 = st.columns(3)
with c1:
    default_strike = float(round(s0/50)*50) if "NIFTY" in asset else float(round(s0/10)*10)
    strike = st.number_input("Strike Price", value=default_strike, step=50.0 if "NIFTY" in asset else 10.0)

# DYNAMIC CALL/PUT LOOKUP
with c2:
    val_c = 0.0
    if not calls_df.empty and strike in calls_df['strike'].values:
        val_c = calls_df[calls_df['strike'] == strike]['lastPrice'].values[0]
    
    if val_c <= 0 or np.isnan(val_c):
        val_c = round(s0 * 0.025, 2)
    # The 'value' is now tied to val_c, making it update when strike changes
    c_mkt = st.number_input("Call Price", value=float(val_c), key="call_input")

with c3:
    val_p = 0.0
    if not puts_df.empty and strike in puts_df['strike'].values:
        val_p = puts_df[puts_df['strike'] == strike]['lastPrice'].values[0]
        
    if val_p <= 0 or np.isnan(val_p):
        val_p = round(s0 * 0.018, 2)
    # The 'value' is now tied to val_p
    p_mkt = st.number_input("Put Price", value=float(val_p), key="put_input")

# --- 4. CALCULATIONS ---
t = days_to_expiry / 365
pv_k = strike * np.exp(-r_rate * t)
synthetic_spot = c_mkt - p_mkt + pv_k
spread_per_unit = s0 - synthetic_spot
total_friction = (brokerage * 3 * num_lots) + (s0 * total_units * 0.001)
capital_req = (s0 * total_units) * margin_pct

# Signal Logic
if spread_per_unit > 0.1:
    signal_line, signal_color, strategy_desc = "CONVERSION ARBITRAGE DETECTED", "#28a745", "Buy Spot, Buy Put, Sell Call"
    net_pnl = (spread_per_unit * total_units) - total_friction
elif spread_per_unit < -0.1:
    signal_line, signal_color, strategy_desc = "REVERSAL ARBITRAGE DETECTED", "#dc3545", "Short Spot, Sell Put, Buy Call"
    net_pnl = (abs(spread_per_unit) * total_units) - total_friction
else:
    signal_line, signal_color, net_pnl, strategy_desc = "MARKET IS EFFICIENT", "#6c757d", 0.0, "No Action"

# --- 5. UI DISPLAY ---
m1, m2, m3, m4 = st.columns(4)
m1.metric("Market Spot", f"₹{s0:,.2f}")
m2.metric("Synthetic Price", f"₹{synthetic_spot:,.2f}")
m3.metric("Arbitrage Gap", f"₹{abs(spread_per_unit):.2f}")
m4.metric("Capital Req.", f"₹{capital_req:,.0f}")

st.markdown(f'<div style="background-color:{signal_color}; padding:15px; border-radius:10px; text-align:center; color:white;"><h2 style="margin:0;">{signal_line}</h2><p style="margin:0;">Expiry: {current_expiry}</p></div>', unsafe_allow_html=True)

st.write("")
col_proof, col_graph = st.columns([1, 1.2])

with col_proof:
    st.subheader("📊 Execution Proof")
    st.markdown(f'<div class="strategy-text">Strategy: {strategy_desc}</div>', unsafe_allow_html=True)
    st.latex(r"P = Units \times [ (S_{T} - S_{0}) + (K - S_{T})^{+} - (S_{T} - K)^{+} + (C - P) ]")
    st.metric("Final Net Profit", f"₹{net_pnl:,.2f}")
    st.write(f"Profit is locked for {total_units} units.")

with col_graph:
    prices = np.linspace(s0*0.8, s0*1.2, 10)
    fig = go.Figure(go.Scatter(x=prices, y=[net_pnl]*10, mode='lines', line=dict(color=signal_color, width=4)))
    fig.update_layout(title="Risk-Neutral Payoff", height=280, margin=dict(t=30, b=0, l=0, r=0))
    st.plotly_chart(fig, use_container_width=True)

# --- 6. SCENARIO TABLE ---
st.divider()
st.subheader("📉 Expiry Scenario Analysis")
scenarios = [s0 * 0.9, s0, s0 * 1.1]
pdf = [{"Price at Expiry": f"₹{p:,.0f}", "Lot Size": lot, "Total Units": total_units, "TOTAL NET": f"₹{net_pnl:,.2f}"} for p in scenarios]
st.table(pd.DataFrame(pdf))
