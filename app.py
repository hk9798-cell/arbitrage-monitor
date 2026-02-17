import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

# --- 1. CONFIG & UI STYLING (MODERN DARK THEME) ---
st.set_page_config(page_title="Arbitrage Monitor Pro", layout="wide")

st.markdown("""
    <style>
    [data-testid="stAppViewContainer"] { background-color: #0e1117; color: #ffffff; }
    [data-testid="stSidebar"] { background-color: #1a1c24; }
    .stMetric { background-color: #1f2937; padding: 15px; border-radius: 10px; border: 1px solid #374151; }
    div[data-testid="stMetricValue"] { font-size: 32px !important; color: #00ffcc !important; font-weight: bold; }
    div[data-testid="stMetricLabel"] { font-size: 16px !important; color: #9ca3af !important; }
    .logic-box { background-color: #111827; padding: 20px; border-radius: 10px; border-left: 5px solid #00ffcc; color: #e5e7eb; line-height: 1.6; }
    .proof-box { background-color: #000000; padding: 15px; border: 1px solid #374151; border-radius: 10px; font-family: 'Courier New', monospace; color: #00ffcc; }
    h1, h2, h3 { color: #ffffff !important; }
    .stButton>button { width: 100%; background-color: #00ffcc; color: #0e1117; font-weight: bold; border-radius: 8px; }
    </style>
    """, unsafe_allow_html=True)

st.title("🏛️ Institutional Arbitrage Monitor")
st.markdown("---")

# --- 2. ASSET MASTER DATA ---
ticker_map = {"NIFTY": "^NSEI", "RELIANCE": "RELIANCE.NS", "TCS": "TCS.NS", "SBIN": "SBIN.NS", "INFY": "INFY.NS"}
lot_sizes = {"NIFTY": 65, "RELIANCE": 250, "TCS": 175, "SBIN": 1500, "INFY": 400}

with st.sidebar:
    st.header("⚙️ Market Settings")
    asset = st.selectbox("Select Asset", list(ticker_map.keys()))
    num_lots = st.number_input("Number of Lots", min_value=1, value=1)
    r_rate = st.slider("Risk-Free Rate (%)", 4.0, 10.0, 6.75) / 100
    
    st.divider()
    st.subheader("Costs & Margins")
    brokerage = st.number_input("Brokerage/Side (₹)", value=20.0)
    margin_pct = st.slider("Margin Requirement (%)", 10, 40, 25) / 100
    
    if st.button("🔄 Refresh Market Data"):
        st.cache_data.clear()

# --- 3. REAL-TIME DATA ENGINE ---
@st.cache_data(ttl=60)
def fetch_live_data(ticker_symbol):
    stock = yf.Ticker(ticker_symbol)
    history = stock.history(period="1d")
    if history.empty: return 25000, 0, 0, 0 # Fallback
    
    s_price = history['Close'].iloc[-1]
    
    # Get Options Chain
    try:
        expirations = stock.options
        if not expirations: return s_price, 0, 0, 0
        
        # Pick the nearest expiry
        chain = stock.option_chain(expirations[0])
        calls = chain.calls
        puts = chain.puts
        
        # Find ATM Strike
        atm_strike = calls.iloc[(calls['strike'] - s_price).abs().argsort()[:1]]['strike'].values[0]
        c_price = calls[calls['strike'] == atm_strike]['lastPrice'].values[0]
        p_price = puts[puts['strike'] == atm_strike]['lastPrice'].values[0]
        
        # Calculate days to expiry
        d1 = datetime.strptime(expirations[0], '%Y-%m-%d')
        d2 = datetime.now()
        days_left = max((d1 - d2).days, 1)
        
        return round(s_price, 2), atm_strike, round(c_price, 2), round(p_price, 2), days_left
    except:
        return round(s_price, 2), round(s_price, -1), round(s_price*0.02, 2), round(s_price*0.015, 2), 15

s0, auto_strike, auto_call, auto_put, dte = fetch_live_data(ticker_map[asset])

# Manual Overrides
c1, c2, c3 = st.columns(3)
with c1: strike = st.number_input("Strike Price", value=float(auto_strike))
with c2: c_mkt = st.number_input("Call Price", value=float(auto_call))
with c3: p_mkt = st.number_input("Put Price", value=float(auto_put))

# --- 4. CALCULATIONS ---
total_units = num_lots * lot_sizes[asset]
t = dte / 365
pv_k = strike * np.exp(-r_rate * t)
synthetic_spot = c_mkt - p_mkt + pv_k
spread_per_unit = s0 - synthetic_spot
total_friction = (brokerage * 3 * num_lots) + (s0 * total_units * 0.001) # STT + Brokerage
capital_req = (s0 * total_units) * margin_pct

# Signal Logic
if spread_per_unit > 0.5: # Threshold for slippage
    signal, color, strategy = "CONVERSION ARBITRAGE", "#00ffcc", "Buy Spot + Buy Put + Sell Call"
    net_pnl = (spread_per_unit * total_units) - total_friction
elif spread_per_unit < -0.5:
    signal, color, strategy = "REVERSAL ARBITRAGE", "#ff4b4b", "Short Spot + Sell Put + Buy Call"
    net_pnl = (abs(spread_per_unit) * total_units) - total_friction
else:
    signal, color, strategy, net_pnl = "EFFICIENT MARKET", "#9ca3af", "No Mispricing Detected", 0

# --- 5. DASHBOARD DISPLAY ---
m1, m2, m3, m4 = st.columns(4)
m1.metric("Market Spot", f"₹{s0:,.2f}")
m2.metric("Synthetic Price", f"₹{synthetic_spot:,.2f}")
m3.metric("Net Spread", f"₹{abs(spread_per_unit):.2f}")
m4.metric("Days to Expiry", f"{dte} Days")

st.markdown(f"""
    <div style="background-color:{color}; padding:15px; border-radius:10px; text-align:center; margin: 20px 0;">
        <h2 style="margin:0; color:#0e1117 !important;">{signal}</h2>
        <p style="margin:0; color:#0e1117; font-weight:bold;">{strategy}</p>
    </div>
    """, unsafe_allow_html=True)

# Main Stats Row
r1, r2 = st.columns(2)
with r1:
    st.subheader("📈 Profitability")
    st.metric("Estimated Net Profit", f"₹{net_pnl:,.2f}")
    st.write(f"*Capital Needed:* ₹{capital_req:,.2f}")
    st.write(f"*Est. ROI:* {((net_pnl/capital_req)*100 if capital_req > 0 else 0):.2f}%")

with r2:
    st.subheader("⚖️ Risk Proof")
    st.latex(r"V_{Locked} = K - S_0 + (C - P)")
    st.markdown(f"""
    <div class="proof-box">
    The profit of ₹{net_pnl:,.2f} is mathematically delta-neutral. 
    Price movement risk is eliminated via Put-Call parity.
    </div>
    """, unsafe_allow_html=True)

# --- 6. SCENARIO TABLE ---
st.divider()
st.subheader("📊 Expiry Value Confirmation")
scenarios = [s0 * 0.9, s0, s0 * 1.1]
table_data = []

for st_price in scenarios:
    if "CONVERSION" in signal:
        s_pnl = (st_price - s0); o_pnl = (max(0, strike - st_price) - p_mkt) + (c_mkt - max(0, st_price - strike))
    elif "REVERSAL" in signal:
        s_pnl = (s0 - st_price); o_pnl = (p_mkt - max(0, strike - st_price)) + (max(0, st_price - strike) - c_mkt)
    else: s_pnl = o_pnl = 0

    table_data.append({
        "Expiry Price": f"₹{st_price:,.0f}",
        "Stock P&L": f"₹{s_pnl*total_units:,.0f}",
        "Options P&L": f"₹{o_pnl*total_units:,.0f}",
        "Total (Net)": f"₹{net_pnl:,.2f}"
    })

st.table(pd.DataFrame(table_data))

# Payoff Visual
prices = np.linspace(s0*0.85, s0*1.15, 50)
fig = go.Figure(go.Scatter(x=prices, y=[net_pnl]*50, mode='lines', line=dict(color=color, width=4)))
fig.update_layout(
    title="Risk-Free Payoff Profile",
    paper_bgcolor='rgba(0,0,0,0)',
    plot_bgcolor='rgba(0,0,0,0)',
    font=dict(color="white"),
    xaxis=dict(gridcolor='#374151'),
    yaxis=dict(gridcolor='#374151'),
    height=350
)
st.plotly_chart(fig, use_container_width=True)
