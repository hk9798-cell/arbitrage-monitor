import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go

# --- 1. APP CONFIG ---
st.set_page_config(page_title="Arbitrage Monitor", layout="wide")

# Custom CSS for a professional look
st.markdown("""
    <style>
    .main { background-color: #f8f9fa; }
    div[data-testid="stMetricValue"] { font-size: 22px; font-weight: bold; color: #0e1117; }
    .stTable { font-size: 14px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🏛️ Cross-Asset Arbitrage Opportunity Monitor")

# --- 2. ASSET CONSTANTS ---
ticker_map = {
    "NIFTY": "^NSEI", 
    "RELIANCE": "RELIANCE.NS", 
    "TCS": "TCS.NS", 
    "SBIN": "SBIN.NS", 
    "INFY": "INFY.NS"
}
lot_sizes = {"NIFTY": 65, "RELIANCE": 250, "TCS": 175, "SBIN": 1500, "INFY": 400}
strike_steps = {"NIFTY": 50.0, "RELIANCE": 20.0, "TCS": 20.0, "SBIN": 5.0, "INFY": 10.0}

# --- 3. SIDEBAR PARAMETERS ---
with st.sidebar:
    st.header("⚙️ Parameters")
    asset = st.selectbox("Select Asset", list(ticker_map.keys()))
    num_lots = st.number_input("Number of Lots", min_value=1, value=1)
    r_rate = st.slider("Risk-Free Rate (%)", 4.0, 10.0, 6.75) / 100
    days_to_expiry = st.number_input("Days to Expiry", value=15, min_value=1)
    st.divider()
    brokerage = st.number_input("Brokerage per Side (₹)", value=20.0)
    margin_pct = st.slider("Margin Requirement (%)", 10, 40, 20) / 100

# --- 4. STABLE DATA ENGINE ---
@st.cache_data(ttl=30)
def get_live_data(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        # Fetching spot price
        hist = ticker.history(period="1d")
        if hist.empty:
            return 0.0, pd.DataFrame(), pd.DataFrame(), "No Market Connection"
        
        spot = hist['Close'].iloc[-1]
        
        # Robust expiry retrieval to prevent "Fetching Expiry..." hang
        expiries = ticker.options
        if expiries:
            target_expiry = expiries[0]
            chain = ticker.option_chain(target_expiry)
            return round(spot, 2), chain.calls, chain.puts, target_expiry
        
        return round(spot, 2), pd.DataFrame(), pd.DataFrame(), "No Option Chain Found"
    except Exception:
        return 0.0, pd.DataFrame(), pd.DataFrame(), "Data Offline"

s0, calls, puts, expiry_label = get_live_data(ticker_map[asset])
step = strike_steps[asset]

# --- 5. STRIKE & PRICE INPUTS (FIXED RESET) ---
# We use key=asset to ensure the strike resets when you change the ticker
col1, col2, col3 = st.columns(3)
with col1:
    suggested_strike = float(round(s0 / step) * step) if s0 > 0 else 0.0
    strike = st.number_input("Strike Price", value=suggested_strike, step=step, key=f"strike_{asset}")

with col2:
    l_call = 0.0
    if not calls.empty:
        match = calls[calls['strike'] == strike]
        if not match.empty:
            l_call = match['lastPrice'].values[0]
    # Use key with asset and strike to force refresh
    c_price = st.number_input("Call Price (LTP)", value=float(l_call), key=f"c_{asset}_{strike}")

with col3:
    l_put = 0.0
    if not puts.empty:
        match = puts[puts['strike'] == strike]
        if not match.empty:
            l_put = match['lastPrice'].values[0]
    p_price = st.number_input("Put Price (LTP)", value=float(l_put), key=f"p_{asset}_{strike}")

# --- 6. ARBITRAGE CALCULATIONS ---
t = days_to_expiry / 365
pv_k = strike * np.exp(-r_rate * t)
synthetic = c_price - p_price + pv_k
gap = s0 - synthetic
total_units = num_lots * lot_sizes[asset]
friction = (brokerage * 3 * num_lots) + (s0 * total_units * 0.001)

if gap > 0.5:
    status, color, strategy = "CONVERSION ARBITRAGE DETECTED", "#28a745", "Buy Spot + Buy Put + Sell Call"
    net_pnl = (gap * total_units) - friction
elif gap < -0.5:
    status, color, strategy = "REVERSAL ARBITRAGE DETECTED", "#dc3545", "Short Spot + Sell Put + Buy Call"
    net_pnl = (abs(gap) * total_units) - friction
else:
    status, color, net_pnl, strategy = "MARKET IS EFFICIENT", "#6c757d", 0.0, "No Action"

# --- 7. DASHBOARD DISPLAY ---
m1, m2, m3, m4 = st.columns(4)
m1.metric("Market Spot", f"₹{s0:,.2f}")
m2.metric("Synthetic", f"₹{synthetic:,.2f}")
m3.metric("Arb. Gap", f"₹{abs(gap):.2f}")
m4.metric("Capital", f"₹{(s0 * total_units * margin_pct):,.0f}")

st.markdown(f"""
    <div style="background-color:{color}; padding:15px; border-radius:8px; text-align:center; color:white;">
        <h2 style="margin:0;">{status}</h2>
        <p style="margin:0; font-weight:bold;">Expiry: {expiry_label}</p>
    </div>
    """, unsafe_allow_html=True)

st.write("")
left, right = st.columns([1, 1.2])

with left:
    st.subheader("📊 Execution Proof")
    st.write(f"*Strategy:* {strategy}")
    st.latex(r"P = Units \times [ (S_{T} - S_{0}) + (K - S_{T})^{+} - (S_{T} - K)^{+} + (C - P) ]")
    st.metric("Net PnL", f"₹{net_pnl:,.2f}")

with right:
    # Payoff visualization
    px_range = np.linspace(s0*0.9, s0*1.1, 10) if s0 > 0 else np.linspace(100, 200, 10)
    fig = go.Figure(go.Scatter(x=px_range, y=[net_pnl]*10, mode='lines', line=dict(color=color, width=4)))
    fig.update_layout(title="Risk-Neutral Payoff", height=250, margin=dict(t=30, b=0, l=0, r=0))
    st.plotly_chart(fig, use_container_width=True)

# --- 8. SCENARIO ANALYSIS TABLE ---
st.divider()
st.subheader("📉 Expiry Scenario Analysis")
scenario_prices = [s0 * 0.9, s0, s0 * 1.1] if s0 > 0 else [0, 0, 0]
table_data = []
for price in scenario_prices:
    table_data.append({
        "Price at Expiry": f"₹{price:,.0f}",
        "Lot Size": lot_sizes[asset],
        "Total Units": total_units,
        "TOTAL NET PnL": f"₹{net_pnl:,.2f}"
    })
st.table(pd.DataFrame(table_data))
