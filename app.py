import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

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
lot_sizes = {"NIFTY": 65, "RELIANCE": 250, "TCS": 175, "SBIN": 1500, "INFY": 400}

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
    stt_pct = 0.001 # 0.1% STT

# --- 3. DATA ENGINE ---
@st.cache_data(ttl=30)
def get_market_data(ticker):
    stock = yf.Ticker(ticker)
    hist = stock.history(period="1d")
    if hist.empty:
        return 2500.0, 2510.0 
    spot = hist['Close'].iloc[-1]
    fair_future = spot * np.exp(r_rate * t)
    return round(spot, 2), round(fair_future, 2)

s0, fair_f = get_market_data(ticker_map[asset])

# Manual inputs for Option prices
c1, c2, c3 = st.columns(3)
strike = c1.number_input("ATM Strike Price", value=float(round(s0/50)*50 if asset=="NIFTY" else round(s0/10)*10))
c_mkt = c2.number_input("Call Market Price", value=round(s0*0.02, 2))
p_mkt = c3.number_input("Put Market Price", value=round(s0*0.015, 2))

# --- 4. FUNDAMENTAL PARITY CALCULATIONS ---
# Put-Call Parity: C - P = S - K*exp(-rt)
synthetic_spot = c_mkt - p_mkt + (strike * np.exp(-r_rate * t))
spread = s0 - synthetic_spot
lot = lot_sizes[asset]
total_cost_per_unit = ((brokerage * 3) / lot) + (s0 * stt_pct)

# --- 5. DASHBOARD VISUALS ---
m1, m2, m3 = st.columns(3)
m1.metric("Actual Spot Price", f"₹{s0:,.2f}")
m2.metric("Synthetic Fair Price", f"₹{synthetic_spot:,.2f}")
m3.metric("Arbitrage Gap", f"₹{abs(spread):.2f}", delta=f"{spread:.2f} (Pre-Cost)")

st.divider()

# --- 6. EXECUTION STEPS & P&L ---
col_left, col_right = st.columns([1, 1])
trade_steps = []

with col_left:
    st.subheader("🛠️ Execution Strategy")
    if spread > 1.0: 
        st.success("🎯 SIGNAL: CONVERSION ARBITRAGE")
        trade_steps = [
            {"Action": "SELL", "Instrument": f"{asset} CALL", "Strike": strike, "Qty": lot, "Price": c_mkt},
            {"Action": "BUY", "Instrument": f"{asset} PUT", "Strike": strike, "Qty": lot, "Price": p_mkt},
            {"Action": "BUY", "Instrument": f"{asset} UNDERLYING", "Strike": "N/A", "Qty": lot, "Price": s0}
        ]
        net_profit = (spread - total_cost_per_unit) * lot
    elif spread < -1.0:
        st.error("🎯 SIGNAL: REVERSAL ARBITRAGE")
        trade_steps = [
            {"Action": "BUY", "Instrument": f"{asset} CALL", "Strike": strike, "Qty": lot, "Price": c_mkt},
            {"Action": "SELL", "Instrument": f"{asset} PUT", "Strike": strike, "Qty": lot, "Price": p_mkt},
            {"Action": "SELL/SHORT", "Instrument": f"{asset} UNDERLYING", "Strike": "N/A", "Qty": lot, "Price": s0}
        ]
        net_profit = (abs(spread) - total_cost_per_unit) * lot
    else:
        st.warning("⚖️ Market is Efficient. No Arbitrage detected.")
        net_profit = 0

    if trade_steps:
        df_trade = pd.DataFrame(trade_steps)
        st.table(df_trade)
        
        csv = df_trade.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Trade Report (CSV)",
            data=csv,
            file_name=f"arb_report_{asset}_{datetime.now().strftime('%Y%m%d')}.csv",
            mime='text/csv',
        )

with col_right:
    st.subheader("📊 Profit Profile")
    st.metric("Estimated Net Profit (1 Lot)", f"₹{net_profit:,.2f}")
    
    # Plotly Chart
    prices = np.linspace(s0*0.9, s0*1.1, 10)
    pnl_line = [net_profit for _ in prices]
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=prices, y=pnl_line, name="Locked Profit", line=dict(color='gold', width=4)))
    fig.update_layout(height=300, margin=dict(l=20, r=20, t=30, b=20), xaxis_title="Expiry Price", yaxis_title="Profit (₹)")
    st.plotly_chart(fig, use_container_width=True)

    # --- THE PROOF SECTION ---
    with st.expander("🔍 See Mathematical Proof"):
        st.write("Arbitrage profit is fixed because your 'Delta' is zero.")
        st.latex(r"Profit = (S_{T} - S_{0}) + (K - S_{T})^{+} - (S_{T} - K)^{+} + (C - P)")
        st.info(f"Whether {asset} ends at ₹{s0*0.5:,.0f} or ₹{s0*1.5:,.0f}, your total return is locked at ₹{net_profit:,.2f} (excluding friction).")
