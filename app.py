import streamlit as st
import yfinance as yf
import numpy as np
import pandas as pd
import plotly.graph_objects as go

# ─────────────────────────────────────────────────────────────────────────────
# 1. CONFIG & UI STYLING
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="Arbitrage Monitor", layout="wide")

st.markdown("""
    <style>
    .main { background-color: #f0f2f6; }

    label[data-testid="stWidgetLabel"] p {
        font-weight: bold !important;
        font-size: 15px !important;
    }
    div[data-testid="stMetricLabel"] p {
        font-weight: bold !important;
        font-size: 14px !important;
    }
    div[data-testid="stMetricValue"] {
        font-size: 26px;
        color: #1f77b4;
        font-weight: bold;
    }
    .strategy-text {
        font-weight: bold;
        font-size: 17px;
        margin-bottom: 5px;
    }
    .warning-box {
        background-color: #fff3cd;
        border-left: 5px solid #ffc107;
        padding: 10px 16px;
        border-radius: 6px;
        color: #856404;
        font-weight: 500;
        margin-top: 8px;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🏛️ Cross-Asset Arbitrage Opportunity Monitor")

# ─────────────────────────────────────────────────────────────────────────────
# 2. ASSET MASTER DATA
# ─────────────────────────────────────────────────────────────────────────────
TICKER_MAP = {
    "NIFTY":    "^NSEI",
    "RELIANCE": "RELIANCE.NS",
    "TCS":      "TCS.NS",
    "SBIN":     "SBIN.NS",
    "INFY":     "INFY.NS",
}

LOT_SIZES = {
    "NIFTY":    65,
    "RELIANCE": 250,
    "TCS":      175,
    "SBIN":     1500,
    "INFY":     400,
}

# Per-asset sensible strike rounding and step sizes
STRIKE_STEP = {
    "NIFTY":    50,
    "RELIANCE": 20,
    "TCS":      50,
    "SBIN":     5,
    "INFY":     20,
}

# Realistic per-asset fallback spot prices (updated periodically)
FALLBACK_SPOTS = {
    "NIFTY":    24500.0,
    "RELIANCE": 1280.0,
    "TCS":      3850.0,
    "SBIN":     810.0,
    "INFY":     1580.0,
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. SIDEBAR PARAMETERS
# ─────────────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Parameters")
    asset = st.selectbox("Select Asset", list(TICKER_MAP.keys()))
    num_lots = st.number_input("Number of Lots", min_value=1, value=1, step=1)
    r_rate = st.slider("Risk-Free Rate (%)", 4.0, 10.0, 6.75, step=0.25) / 100
    days_to_expiry = st.number_input("Days to Expiry", value=15, min_value=1, max_value=365)
    st.divider()
    brokerage = st.number_input("Brokerage per Order (₹)", value=20.0, min_value=0.0, step=5.0,
                                 help="Flat fee charged per order/side by your broker (e.g. Zerodha ₹20)")
    margin_pct = st.slider("Margin Requirement (%)", 10, 40, 20) / 100
    st.divider()
    # FIX 5: Threshold should be % of spot so it scales across assets
    arb_threshold_pct = st.slider(
        "Arbitrage Threshold (%)",
        min_value=0.01, max_value=0.5, value=0.05, step=0.01,
        help="Minimum gap (as % of spot) to flag an arbitrage. Prevents noise from bid-ask spread."
    )

# ─────────────────────────────────────────────────────────────────────────────
# 4. DATA ENGINE
# FIX 1: Cache key includes asset so switching assets always fetches fresh data
# FIX 9: Cache key = (ticker, asset) — distinct per asset
# FIX 13: Bare except replaced with except Exception
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=60, show_spinner=False)
def get_market_data(ticker: str, asset_name: str):
    """
    Fetch live spot price and nearest-expiry option chain.
    Returns (spot, calls_df, puts_df, expiry_date, error_msg).
    """
    try:
        stock = yf.Ticker(ticker)
        hist = stock.history(period="2d")  # 2 days for reliability

        if hist.empty or "Close" not in hist.columns:
            raise ValueError("No historical price data returned.")

        spot = float(round(hist["Close"].iloc[-1], 2))

        if not stock.options:
            return spot, pd.DataFrame(), pd.DataFrame(), None, "No options data available for this asset."

        expiry = stock.options[0]
        chain = stock.option_chain(expiry)
        calls = chain.calls.copy()
        puts = chain.puts.copy()

        # Normalise strike column to float
        calls["strike"] = calls["strike"].astype(float)
        puts["strike"] = puts["strike"].astype(float)

        return spot, calls, puts, expiry, None

    except Exception as e:
        fallback = FALLBACK_SPOTS[asset_name]
        return fallback, pd.DataFrame(), pd.DataFrame(), None, str(e)


# ─────────────────────────────────────────────────────────────────────────────
# 5. FETCH DATA WITH SPINNER
# FIX 10: Show loading indicator while fetching
# ─────────────────────────────────────────────────────────────────────────────
with st.spinner(f"Fetching live data for {asset}..."):
    s0, calls_df, puts_df, expiry_date, fetch_error = get_market_data(TICKER_MAP[asset], asset)

if fetch_error:
    st.warning(f"⚠️ Live data issue: {fetch_error}  |  Using fallback spot price: ₹{s0:,.2f}")

if expiry_date:
    st.caption(f"📅 Option chain loaded for expiry: *{expiry_date}*")

lot = LOT_SIZES[asset]
total_units = num_lots * lot
step = float(STRIKE_STEP[asset])

# ─────────────────────────────────────────────────────────────────────────────
# 6. STRIKE & OPTION PRICE INPUTS
# FIX 11: Strike rounding uses asset-specific step lookup, not string match
# FIX 12: Fallback only applied when option chain is unavailable, not on valid 0
# ─────────────────────────────────────────────────────────────────────────────
c1, c2, c3 = st.columns(3)

with c1:
    default_strike = float(round(s0 / step) * step)
    strike = st.number_input("Strike Price (₹)", value=default_strike, step=step, format="%.2f")

def lookup_option_price(chain_df: pd.DataFrame, target_strike: float) -> float | None:
    """
    FIX 2: Use np.isclose for float strike matching instead of exact equality.
    Returns lastPrice if a close match is found, else None.
    """
    if chain_df.empty:
        return None
    strikes = chain_df["strike"].values
    mask = np.isclose(strikes, target_strike, rtol=0, atol=step * 0.4)
    if not mask.any():
        return None
    price = chain_df.loc[mask, "lastPrice"].values[0]
    # Only use if genuinely traded (non-zero volume or non-zero open interest)
    volume = chain_df.loc[mask, "volume"].values[0] if "volume" in chain_df.columns else np.nan
    oi = chain_df.loc[mask, "openInterest"].values[0] if "openInterest" in chain_df.columns else np.nan
    if price > 0 and (pd.isna(volume) or volume > 0 or (not pd.isna(oi) and oi > 0)):
        return float(round(price, 2))
    return None  # Let user enter manually if stale/zero

with c2:
    live_call = lookup_option_price(calls_df, strike)
    call_default = live_call if live_call is not None else round(s0 * 0.025, 2)
    call_source = "🟢 Live" if live_call is not None else "🟡 Estimated"
    c_mkt = st.number_input(f"Call Price (₹)  {call_source}", value=float(call_default),
                             min_value=0.01, step=0.5, format="%.2f")

with c3:
    live_put = lookup_option_price(puts_df, strike)
    put_default = live_put if live_put is not None else round(s0 * 0.018, 2)
    put_source = "🟢 Live" if live_put is not None else "🟡 Estimated"
    p_mkt = st.number_input(f"Put Price (₹)  {put_source}", value=float(put_default),
                              min_value=0.01, step=0.5, format="%.2f")

# ─────────────────────────────────────────────────────────────────────────────
# 7. CORE CALCULATIONS
# ─────────────────────────────────────────────────────────────────────────────
t = days_to_expiry / 365.0
pv_k = strike * np.exp(-r_rate * t)

# Synthetic spot from Put-Call Parity: S_synthetic = C - P + PV(K)
synthetic_spot = c_mkt - p_mkt + pv_k

# Mispricing: positive = Conversion, negative = Reversal
spread_per_unit = s0 - synthetic_spot

# FIX 3: Correct brokerage model
# Legs per trade:
#   Conversion : Buy Spot (1) + Buy Put (1) + Sell Call (1) = 3 orders in
#                Sell Spot (1) + Sell Put/Call at expiry = 2 orders out  → 5 sides
#   We use 4 as a conservative but standard model: entry (3 legs) + 1 exit hedge
#   Using num_lots for F&O legs and 1 for the spot transaction
fno_orders = 2 * num_lots          # Call + Put (1 buy, 1 sell)
spot_orders = 2                    # Buy and sell spot (round trip)
total_brokerage = brokerage * (fno_orders + spot_orders)

# STT on spot: 0.1% on buy side; STT on options sell side: 0.0625% of premium
stt_spot = s0 * total_units * 0.001
stt_options = (c_mkt + p_mkt) * total_units * 0.000625
total_friction = total_brokerage + stt_spot + stt_options

gross_spread = spread_per_unit * total_units

# FIX 5: Threshold scaled to spot price
arb_threshold = s0 * (arb_threshold_pct / 100)

# ─────────────────────────────────────────────────────────────────────────────
# 8. SIGNAL LOGIC
# FIX 4: Always compute net_pnl; show warning if negative (friction > spread)
# ─────────────────────────────────────────────────────────────────────────────
if spread_per_unit > arb_threshold:
    signal_line   = "CONVERSION ARBITRAGE DETECTED"
    signal_color  = "#28a745"
    strategy_desc = "Buy Spot  ·  Buy Put  ·  Sell Call"
    signal_type   = "conversion"
    net_pnl = abs(gross_spread) - total_friction

elif spread_per_unit < -arb_threshold:
    signal_line   = "REVERSAL ARBITRAGE DETECTED"
    signal_color  = "#dc3545"
    strategy_desc = "Short Spot  ·  Sell Put  ·  Buy Call"
    signal_type   = "reversal"
    net_pnl = abs(gross_spread) - total_friction

else:
    signal_line   = "MARKET IS EFFICIENT — No Arbitrage"
    signal_color  = "#6c757d"
    strategy_desc = "No Action"
    signal_type   = "none"
    net_pnl = -total_friction  # Still shows friction cost if user were to trade

pnl_is_profitable = net_pnl > 0

# ─────────────────────────────────────────────────────────────────────────────
# 9. METRICS ROW
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("---")
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Market Spot",      f"₹{s0:,.2f}")
m2.metric("Synthetic Price",  f"₹{synthetic_spot:,.2f}")
m3.metric("Arbitrage Gap",    f"₹{abs(spread_per_unit):.2f}",
          delta=f"Threshold ₹{arb_threshold:.2f}",
          delta_color="off")
m4.metric("Total Friction",   f"₹{total_friction:,.2f}")
m5.metric("Capital Required", f"₹{(s0 * total_units * margin_pct):,.0f}")

# Signal Banner
st.markdown(
    f'<div style="background-color:{signal_color}; padding:14px; border-radius:10px; '
    f'text-align:center; color:white; margin-top:12px;">'
    f'<h2 style="margin:0; font-size:22px;">{signal_line}</h2>'
    f'<p style="margin:4px 0 0 0; font-size:15px; opacity:0.9;">Strategy: {strategy_desc}</p>'
    f'</div>',
    unsafe_allow_html=True
)

# FIX 4: Warn if friction makes net PnL negative
if signal_type != "none" and not pnl_is_profitable:
    st.markdown(
        '<div class="warning-box">⚠️ <strong>Arbitrage gap detected but NOT profitable after costs.</strong> '
        'Friction (brokerage + STT) exceeds the gross spread. Do not trade.</div>',
        unsafe_allow_html=True
    )

st.write("")

# ─────────────────────────────────────────────────────────────────────────────
# 10. EXECUTION PROOF + PAYOFF CHART
# FIX 6: Real payoff chart showing leg P&L vs expiry price
# FIX 8: Corrected LaTeX showing actual put-call parity relationship
# ─────────────────────────────────────────────────────────────────────────────
col_proof, col_graph = st.columns([1, 1.4])

with col_proof:
    st.subheader("📊 Execution Proof")
    st.markdown(f'<div class="strategy-text">Strategy: {strategy_desc}</div>', unsafe_allow_html=True)

    # Corrected formula: the no-arbitrage condition being exploited
    st.latex(r"C - P = S_0 - K \cdot e^{-rT} \quad \text{(Put-Call Parity)}")
    st.latex(r"\text{Gap} = S_0 - (C - P + K e^{-rT})")

    st.markdown("*Cost Breakdown:*")
    cost_df = pd.DataFrame({
        "Item": ["Brokerage (4 orders)", "STT on Spot", "STT on Options", "Total Friction"],
        "Amount (₹)": [
            f"₹{total_brokerage:,.2f}",
            f"₹{stt_spot:,.2f}",
            f"₹{stt_options:,.2f}",
            f"*₹{total_friction:,.2f}*",
        ]
    })
    st.dataframe(cost_df, hide_index=True, use_container_width=True)

    pnl_color = "normal" if pnl_is_profitable else "inverse"
    st.metric(
        "Net Profit (after all costs)",
        f"₹{net_pnl:,.2f}",
        delta="Profitable ✅" if pnl_is_profitable else "Loss after costs ❌",
        delta_color=pnl_color,
    )
    st.caption(f"Across {total_units:,} units ({num_lots} lot{'s' if num_lots > 1 else ''} × {lot})")

with col_graph:
    # FIX 6: Compute actual leg payoffs at each expiry price
    prices = np.linspace(s0 * 0.75, s0 * 1.25, 200)

    if signal_type == "conversion":
        # Long spot: (ST - S0) * units
        spot_pnl   = (prices - s0) * total_units
        # Long put: max(K - ST, 0) - P_premium) * units
        put_pnl    = (np.maximum(strike - prices, 0) - p_mkt) * total_units
        # Short call: (C_premium - max(ST - K, 0)) * units
        call_pnl   = (c_mkt - np.maximum(prices - strike, 0)) * total_units
        total_pnl  = spot_pnl + put_pnl + call_pnl - total_friction

    elif signal_type == "reversal":
        # Short spot: (S0 - ST) * units
        spot_pnl   = (s0 - prices) * total_units
        # Short put: (P_premium - max(K - ST, 0)) * units
        put_pnl    = (p_mkt - np.maximum(strike - prices, 0)) * total_units
        # Long call: (max(ST - K, 0) - C_premium) * units
        call_pnl   = (np.maximum(prices - strike, 0) - c_mkt) * total_units
        total_pnl  = spot_pnl + put_pnl + call_pnl - total_friction

    else:
        spot_pnl  = np.zeros_like(prices)
        put_pnl   = np.zeros_like(prices)
        call_pnl  = np.zeros_like(prices)
        total_pnl = np.zeros_like(prices)

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=prices, y=spot_pnl, mode="lines",
        name="Spot Leg", line=dict(color="#1f77b4", width=1.5, dash="dot"),
        opacity=0.7
    ))
    fig.add_trace(go.Scatter(
        x=prices, y=put_pnl, mode="lines",
        name="Put Leg", line=dict(color="#ff7f0e", width=1.5, dash="dot"),
        opacity=0.7
    ))
    fig.add_trace(go.Scatter(
        x=prices, y=call_pnl, mode="lines",
        name="Call Leg", line=dict(color="#9467bd", width=1.5, dash="dot"),
        opacity=0.7
    ))
    fig.add_trace(go.Scatter(
        x=prices, y=total_pnl, mode="lines",
        name="Net P&L", line=dict(color=signal_color, width=3),
    ))

    # Zero line
    fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
    # Mark current spot
    fig.add_vline(x=s0, line_dash="dash", line_color="#333333", line_width=1,
                  annotation_text=f"Spot ₹{s0:,.0f}", annotation_position="top")

    fig.update_layout(
        title="Strategy Payoff at Expiry (by Spot Price)",
        xaxis_title="Spot Price at Expiry (₹)",
        yaxis_title="Net P&L (₹)",
        height=340,
        margin=dict(t=40, b=40, l=0, r=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        plot_bgcolor="#f8f9fa",
        paper_bgcolor="white",
    )
    fig.update_xaxes(tickformat="₹,.0f", showgrid=True, gridcolor="#e9ecef")
    fig.update_yaxes(tickformat="₹,.0f", showgrid=True, gridcolor="#e9ecef")

    st.plotly_chart(fig, use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# 11. SCENARIO TABLE — FIX 7: Actual leg-by-leg P&L at each expiry price
# ─────────────────────────────────────────────────────────────────────────────
st.divider()
st.subheader("📉 Expiry Scenario Analysis")
st.caption("Shows actual P&L of each leg at different expiry prices — confirming locked payoff.")

scenario_prices = {
    "Bear (−15%)": s0 * 0.85,
    "Bear (−10%)": s0 * 0.90,
    "At Strike":   strike,
    "At Money":    s0,
    "Bull (+10%)": s0 * 1.10,
    "Bull (+15%)": s0 * 1.15,
}

rows = []
for label, st_price in scenario_prices.items():
    if signal_type == "conversion":
        s_leg   = (st_price - s0) * total_units
        p_leg   = (max(strike - st_price, 0) - p_mkt) * total_units
        c_leg   = (c_mkt - max(st_price - strike, 0)) * total_units
    elif signal_type == "reversal":
        s_leg   = (s0 - st_price) * total_units
        p_leg   = (p_mkt - max(strike - st_price, 0)) * total_units
        c_leg   = (max(st_price - strike, 0) - c_mkt) * total_units
    else:
        s_leg = p_leg = c_leg = 0.0

    gross   = s_leg + p_leg + c_leg
    net     = gross - total_friction

    rows.append({
        "Scenario":       label,
        "Expiry Price":   f"₹{st_price:,.0f}",
        "Spot Leg (₹)":   f"₹{s_leg:,.2f}",
        "Put Leg (₹)":    f"₹{p_leg:,.2f}",
        "Call Leg (₹)":   f"₹{c_leg:,.2f}",
        "Gross P&L (₹)":  f"₹{gross:,.2f}",
        "Friction (₹)":   f"−₹{total_friction:,.2f}",
        "Net P&L (₹)":    f"₹{net:,.2f}",
    })

scenario_df = pd.DataFrame(rows)
st.dataframe(scenario_df, hide_index=True, use_container_width=True)

# ─────────────────────────────────────────────────────────────────────────────
# 12. SENSITIVITY: HOW MANY LOTS TO BREAK EVEN?
# ─────────────────────────────────────────────────────────────────────────────
if signal_type != "none" and abs(spread_per_unit) > 0:
    st.divider()
    st.subheader("🔍 Break-Even & Sensitivity")

    col_be1, col_be2 = st.columns(2)

    with col_be1:
        # Minimum lots to cover friction
        # net_pnl(n) = |spread| * n * lot - [brokerage*(2*n+2) + stt_spot(n) + stt_options(n)] = 0
        # Solve numerically
        for n in range(1, 501):
            tu = n * lot
            b_cost = brokerage * (2 * n + 2)
            s_stt  = s0 * tu * 0.001
            o_stt  = (c_mkt + p_mkt) * tu * 0.000625
            fric   = b_cost + s_stt + o_stt
            gross_ = abs(spread_per_unit) * tu
            if gross_ >= fric:
                break_even_lots = n
                break
        else:
            break_even_lots = None

        if break_even_lots:
            st.metric("Break-Even Lots", f"{break_even_lots} lots",
                      delta=f"You selected {num_lots} lots",
                      delta_color="normal" if num_lots >= break_even_lots else "inverse")
        else:
            st.warning("This opportunity cannot be made profitable even with 500 lots.")

    with col_be2:
        # Show net PnL vs lot count (1 to min(num_lots*3, 50))
        lot_range = range(1, min(num_lots * 4 + 1, 51))
        pnl_by_lots = []
        for n in lot_range:
            tu = n * lot
            b_cost = brokerage * (2 * n + 2)
            s_stt  = s0 * tu * 0.001
            o_stt  = (c_mkt + p_mkt) * tu * 0.000625
            fric   = b_cost + s_stt + o_stt
            pnl_by_lots.append(abs(spread_per_unit) * tu - fric)

        fig2 = go.Figure()
        fig2.add_trace(go.Bar(
            x=list(lot_range),
            y=pnl_by_lots,
            marker_color=[signal_color if p > 0 else "#dc3545" for p in pnl_by_lots],
            name="Net P&L"
        ))
        fig2.add_hline(y=0, line_dash="dash", line_color="gray")
        fig2.update_layout(
            title="Net P&L vs Number of Lots",
            xaxis_title="Number of Lots",
            yaxis_title="Net P&L (₹)",
            height=260,
            margin=dict(t=35, b=30, l=0, r=0),
            plot_bgcolor="#f8f9fa",
            paper_bgcolor="white",
            showlegend=False,
        )
        fig2.update_yaxes(tickformat="₹,.0f")
        st.plotly_chart(fig2, use_container_width=True)

# ──────────────
