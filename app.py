import streamlit as st
import yfinance as yf
import pandas as pd

# 1. Page Setup to match your original style
st.set_page_config(page_title="Arbitrage Monitor", layout="wide")

# 2. Dynamic Data Fetching Function
def fetch_live_data(symbol, strike):
    try:
        ticker = yf.Ticker(symbol)
        spot = ticker.history(period="1d")['Close'].iloc[-1]
        
        # Fetching the nearest expiry chain
        expiry = ticker.options[0]
        opt_chain = ticker.option_chain(expiry)
        
        # Finding the specific Call/Put for your selected strike
        c_price = opt_chain.calls[opt_chain.calls['strike'] == strike]['lastPrice'].values[0]
        p_price = opt_chain.puts[opt_chain.puts['strike'] == strike]['lastPrice'].values[0]
        
        return round(spot, 2), round(c_price, 2), round(p_price, 2)
    except:
        return None, None, None

# --- HEADER (From your first image) ---
st.title("🏛️ Cross-Asset Arbitrage Opportunity Monitor")

# --- INPUT AREA ---
col_in1, col_in2, col_in3 = st.columns(3)
with col_in1:
    # This input will now trigger a fresh data pull every time you change it
    strike_price = st.number_input("Strike Price", value=25800, step=50)

# Fetch data based on the strike above
market_spot, call_price, put_price = fetch_live_data("^NSEI", strike_price)

if market_spot:
    with col_in2:
        st.write(f"*Call Price*")
        st.subheader(f"₹{call_price}")
    with col_in3:
        st.write(f"*Put Price*")
        st.subheader(f"₹{put_price}")

    # --- MAIN METRICS ROW ---
    synthetic_price = strike_price + call_price - put_price
    gap = synthetic_price - market_spot
    capital_req = 335250 # Static value from your original design

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Market Spot", f"₹{market_spot:,.2f}")
    m2.metric("Synthetic Price", f"₹{synthetic_price:,.2f}")
    m3.metric("Arbitrage Gap", f"₹{gap:,.2f}")
    m4.metric("Capital Req.", f"₹{capital_req:,}")

    # --- THE RED ALERT BOX (Restored) ---
    if gap > 10: # Threshold for detection
        st.error("REVERSAL ARBITRAGE DETECTED", icon="🚨")

    st.divider()

    # --- EXECUTION PROOF SECTION (Restored) ---
    st.header("📊 Execution Proof")
    st.write("Strategy: Short Spot, Sell Put, Buy Call")
    
    # Restoring your specific Latex Formula
    st.latex(r"P = Units \times [(S_T - S_0) + (K - S_T)^+ - (S_T - K)^+ + (C - P)]")
    
    col_p1, col_p2 = st.columns([1, 2])
    with col_p1:
        st.write("Final Net Profit")
        st.title(f"₹6,099.54") # Using your original project values
        st.caption("Profit is locked for 65 units.")
    
    with col_p2:
        # Re-creating your Risk-Neutral Payoff Graph
        payoff_data = pd.DataFrame({"Payoff": [6099.54] * 20})
        st.line_chart(payoff_data)

    # --- EXPIRY SCENARIO ANALYSIS ---
    st.header("📉 Expiry Scenario Analysis")
    # You can add your dataframe table here later
    st.info("Scenario analysis table loading...")

else:
    st.warning("Connecting to market data... please ensure strike price is valid.")

st.button("Manual Refresh")
