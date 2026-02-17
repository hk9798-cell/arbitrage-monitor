import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go

# --- 1. CONFIG & STYLING ---
st.set_page_config(page_title="Cross-Asset Arbitrage Monitor", layout="wide")
st.title("🏛️ Financial Engineering: Cross-Asset Arbitrage Monitor")
st.markdown("Designed for checking violations of *Put-Call Parity* and *Cash-Futures Parity*.")

ticker_map = {
    "NIFTY": "^NSEI", 
    "RELIANCE": "RELIANCE.NS", 
    "TCS": "TCS.NS", 
    "SBIN": "SBIN.NS", 
    "INFY": "INFY.NS"
}
lot_sizes = {"NIFTY": 50, "RELIANCE": 250, "TCS": 175, "SBIN": 1500, "INFY": 400}

# --- 2. SIDEBAR (Parameters) ---
with st.sidebar:
    st.header("⚙️ Model Parameters")
    asset = st.selectbox("Select Asset", list(ticker_map.keys()))
    r_rate = st.slider("Risk-Free Rate (%)", 4.0, 10.0, 6.75) / 100
    days_to_expiry = st.number_input("Days to Expiry", value=15, min_value=1)
    t = days_to_expiry / 365
    
    st.divider()
    st.header("💸 Friction Costs")
    brokerage = st.number_input("Brokerage per side (₹)", value=20.0)
    stt_pct = 0.001 # 0.1% STT on equity delivery

# --- 3. DATA ENGINE ---
@st.cache_data(ttl=30)
def get_market_data(ticker):
    stock = yf.Ticker(ticker)
    spot = stock.history(period="1d")['Close'].iloc[-1]
    # Synthetic Future Price for parity check
    fair_future = spot * np.exp(r_rate * t)
    return round(spot, 2), round(fair_future, 2)

s0, fair_f = get_market_data(ticker_map[asset])

# Manual inputs for Option prices (to simulate mispricing for the demo)
c1, c2, c3 = st.columns(3)
strike = c1.number_input("ATM Strike Price", value=float(round(s0/50)*50 if asset=="NIFTY" else round(s0/10)*10))
c_mkt = c2.number_input("Call Market Price", value=round(s0*0.02, 2))
p_mkt = c3.number_input("Put Market Price", value=round(s0*0.015, 2))

# --- 4. FUNDAMENTAL PARITY CALCULATIONS ---
# Put-Call Parity: C + K*exp(-rt) = P + S
synthetic_spot = c_mkt - p_mkt + (strike * np.exp(-r_rate * t))
spread = s0 - synthetic_spot
lot = lot_sizes[asset]
total_cost = (brokerage * 3) + (s0 * stt_pct * lot / lot) # Simplified per unit cost

# --- 5. DASHBOARD VISUALS ---
m1, m2, m3 = st.columns(3)
m1.metric("Actual Spot Price", f"₹{s0:,.2f}")
m2.metric("Synthetic Fair Price", f"₹{synthetic_spot:,.2f}")
m3.metric("Arbitrage Gap", f"₹{abs(spread):.2f}", delta=f"{spread:.2f} (Pre-Cost)")

# --- 6. EXECUTION STEPS & P&L ---
st.divider()
col_left, col_right = st.columns([1, 1])

with col_left:
    st.subheader("🛠️ Execution Strategy")
    if spread > 1.0: # Arbitrary threshold
        st.success("🎯 SIGNAL: CONVERSION ARBITRAGE")
        st.info(f"""
        *Step-by-Step Execution:*
        1. *SELL* {lot} units of {asset} Call Options (Strike {strike}).
        2. *BUY* {lot} units of {asset} Put Options (Strike {strike}).
        3. *BUY* {lot} units of {asset} Underlying (Cash Market).
        
        Logic: The market price is higher than the synthetic price. Sell the expensive asset, buy the cheap synthetic.
        """)
        net_profit = (spread - total_cost) * lot
    elif spread < -1.0:
        st.error("🎯 SIGNAL: REVERSAL ARBITRAGE")
        st.info(f"""
        *Step-by-Step Execution:*
        1. *BUY* {lot} units of {asset} Call Options (Strike {strike}).
        2. *SELL* {lot} units of {asset} Put Options (Strike {strike}).
        3. *SHORT SELL* {lot} units of {asset} (Futures or Cash).
        
        Logic: The synthetic price is higher than the market price. Buy the cheap market asset, sell the expensive synthetic.
        """)
        net_profit = (abs(spread) - total_cost) * lot
    else:
        st.warning("⚖️ Market is Efficient. No Arbitrage detected.")
        net_profit = 0

with col_right:
    st.subheader("📊 Profit Profile")
    st.metric("Estimated Net Profit (1 Lot)", f"₹{net_profit:,.2f}")
    
    # Visualization of risk-free nature
    prices = np.linspace(s0*0.9, s0*1.1, 10)
    pnl = [net_profit for _ in prices] # Horizontal line because it's arbitrage!
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=prices, y=pnl, name="Arbitrage P&L", line=dict(color='gold', width=4)))
    fig.update_layout(title="Risk-Neutral P&L (Constant across all prices)", xaxis_title="Expiry Price", yaxis_title="Profit (₹)")
    st.plotly_chart(fig, use_container_width=True)

st.caption("Note: This dashboard assumes European style options for NIFTY. Individual stocks in NSE are American-style, which may introduce early-exercise risk.")
