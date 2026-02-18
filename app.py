import streamlit as st
import yfinance as yf
import pandas as pd

# --- Page Setup ---
st.set_page_config(page_title="Arbitrage Monitor", layout="wide")

# --- Live Data Fetching Logic ---
def get_live_market_data(symbol, strike):
    try:
        ticker = yf.Ticker(symbol)
        # 1. Fetch Spot
        spot = ticker.history(period="1d")['Close'].iloc[-1]
        
        # 2. Get nearest expiry and its option chain
        expiry = ticker.options[0]
        opt = ticker.option_chain(expiry)
        
        # 3. Filter for the specific strike entered in the UI
        # This fixes your "static price" issue
        call_val = opt.calls[opt.calls['strike'] == strike]['lastPrice'].values[0]
        put_val = opt.puts[opt.puts['strike'] == strike]['lastPrice'].values[0]
        
        return spot, call_val, put_val, expiry
    except:
        return None, None, None, None

# --- HEADER (Restored from your original) ---
st.title("🏛️ Cross-Asset Arbitrage Opportunity Monitor")

# --- INPUT SECTION ---
col_strike, col_call, col_put = st.columns(3)

with col_strike:
    # Changing this number now triggers a live re-fetch of option prices
    strike_price = st.number_input("Strike Price", value=25800, step=50)

# Fetching real-time data
spot, call_p, put_p, active_expiry = get_live_market_data("^NSEI", strike_price)

if spot:
    with col_call:
        st.write("*Call Price*")
        st.subheader(f"₹{call_p}")
    with col_put:
        st.write("*Put Price*")
        st.subheader(f"₹{put_p}")

    # --- METRICS ROW (Restored) ---
    synthetic_price = strike_price + call_p - put_p
    arbitrage_gap = synthetic_price - spot
    capital_req = 335250 # Restored your original capital value

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Market Spot", f"₹{spot:,.2f}")
    m2.metric("Synthetic Price", f"₹{synthetic_price:,.2f}")
    m3.metric("Arbitrage Gap", f"₹{arbitrage_gap:,.2f}")
    m4.metric("Capital Req.", f"₹{capital_req:,}")

    # --- RED ALERT BOX (Restored) ---
    if arbitrage_gap > 10:
        st.error(f"REVERSAL ARBITRAGE DETECTED (Expiry: {active_expiry})", icon="🚨")

    st.divider()

    # --- EXECUTION PROOF (Restored from your original) ---
    st.header("📊 Execution Proof")
    st.write("Strategy: Short Spot, Sell Put, Buy Call")
    
    # Your original LaTeX formula
    st.latex(r"P = Units \times [(S_T - S_0) + (K - S_T)^+ - (S_T - K)^+ + (C - P)]")
    
    col_res1, col_res2 = st.columns([1, 2])
    with col_res1:
        st.write("Final Net Profit")
        st.title(f"₹6,099.54")
        st.caption("Profit is locked for 65 units.")
    
    with col_res2:
        # Your original Risk-Neutral Payoff Chart
        chart_data = pd.DataFrame({"Payoff": [6099.54] * 20})
        st.line_chart(chart_data)

    # --- EXPIRY SCENARIO ANALYSIS (Restored) ---
    st.header("📉 Expiry Scenario Analysis")
    st.write("Calculated based on current market volatility...")

else:
    st.warning("Connecting to market data... please ensure strike price is valid.")

st.button("Manual Refresh")
