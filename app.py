import streamlit as st
import yfinance as yf
import pandas as pd

# --- Page Config ---
st.set_page_config(page_title="Arbitrage Monitor", layout="wide")

# --- Function to fetch data dynamically ---
def get_market_data(symbol, strike):
    try:
        ticker = yf.Ticker(symbol)
        # Fetch Spot
        spot = ticker.history(period="1d")['Close'].iloc[-1]
        
        # Get nearest expiry option chain
        expiry = ticker.options[0]
        opt = ticker.option_chain(expiry)
        
        # Filter for the specific strike
        call_price = opt.calls[opt.calls['strike'] == strike]['lastPrice'].values[0]
        put_price = opt.puts[opt.puts['strike'] == strike]['lastPrice'].values[0]
        
        return spot, call_price, put_price, expiry
    except:
        return None, None, None, None

# --- UI Layout ---
st.title("🏛️ Cross-Asset Arbitrage Opportunity Monitor")

# Sidebar/Inputs
with st.container():
    col1, col2, col3 = st.columns(3)
    
    with col1:
        # Use a number input to change strike - this triggers a re-run
        strike_price = st.number_input("Strike Price", value=25800, step=50)
    
    # Fetch Data based on the input above
    spot, call, put, expiry = get_market_data("^NSEI", strike_price)

    if spot:
        # --- Calculations (Your features) ---
        # Synthetic Price = Strike + Call - Put
        synthetic = strike_price + call - put
        gap = synthetic - spot
        capital_req = 335250 # Example static value from your screenshot
        
        with col2:
            st.metric("Call Price", f"₹{call}")
        with col3:
            st.metric("Put Price", f"₹{put}")

        st.divider()

        # --- Metrics Row ---
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Market Spot", f"₹{spot:,.2f}")
        m2.metric("Synthetic Price", f"₹{synthetic:,.2f}")
        m3.metric("Arbitrage Gap", f"₹{gap:,.2f}")
        m4.metric("Capital Req.", f"₹{capital_req:,}")

        # --- Alert Logic ---
        if gap > 20: # Example threshold
            st.error(f"REVERSAL ARBITRAGE DETECTED (Expiry: {expiry})")
        else:
            st.info("Market is currently efficient.")

        # --- Execution Proof (Formula from your image) ---
        st.subheader("📊 Execution Proof")
        st.latex(r"P = Units \times [(S_T - S_0) + (K - S_T)^+ - (S_T - K)^+ + (C - P)]")
        
        # Simple Payoff Graph Simulation
        chart_data = pd.DataFrame({"Risk-Neutral Payoff": [6099.54] * 10})
        st.line_chart(chart_data)

    else:
        st.warning("Please wait, fetching live market data or strike not found...")

# --- Footer ---
st.button("Manual Refresh")
