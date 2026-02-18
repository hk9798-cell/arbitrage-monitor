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
    prices = np.linspace(s0 * 0.75, s0 * 1.25, 300)

    if signal_type == "conversion":
        spot_pnl  = (prices - s0) * total_units
        put_pnl   = (np.maximum(strike - prices, 0) - p_mkt) * total_units
        call_pnl  = (c_mkt - np.maximum(prices - strike, 0)) * total_units
        total_pnl = spot_pnl + put_pnl + call_pnl - total_friction
    elif signal_type == "reversal":
        spot_pnl  = (s0 - prices) * total_units
        put_pnl   = (p_mkt - np.maximum(strike - prices, 0)) * total_units
        call_pnl  = (np.maximum(prices - strike, 0) - c_mkt) * total_units
        total_pnl = spot_pnl + put_pnl + call_pnl - total_friction
    else:
        spot_pnl  = np.zeros_like(prices)
        put_pnl   = np.zeros_like(prices)
        call_pnl  = np.zeros_like(prices)
        total_pnl = np.zeros_like(prices)

    # ── DUAL Y-AXIS CHART ──────────────────────────────────────────────
    # Individual legs (left axis) swing massively and cancel each other.
    # Net P&L (right axis) is what actually matters — zoom it properly.
    net_range_pad = max(abs(net_pnl) * 5, 500)   # give net P&L breathing room

    fig = go.Figure()

    # Individual legs on left y-axis (yaxis)
    fig.add_trace(go.Scatter(
        x=prices, y=spot_pnl, mode="lines", name="Spot Leg",
        line=dict(color="#1f77b4", width=1.5, dash="dot"), opacity=0.55,
        yaxis="y1"
    ))
    fig.add_trace(go.Scatter(
        x=prices, y=put_pnl, mode="lines", name="Put Leg",
        line=dict(color="#ff7f0e", width=1.5, dash="dot"), opacity=0.55,
        yaxis="y1"
    ))
    fig.add_trace(go.Scatter(
        x=prices, y=call_pnl, mode="lines", name="Call Leg",
        line=dict(color="#9467bd", width=1.5, dash="dot"), opacity=0.55,
        yaxis="y1"
    ))

    # Net P&L on right y-axis (yaxis2) — zoomed to be clearly visible
    fig.add_trace(go.Scatter(
        x=prices, y=total_pnl, mode="lines", name="Net P&L (right axis)",
        line=dict(color=signal_color, width=3.5),
        yaxis="y2"
    ))

    # Zero line for net axis
    fig.add_shape(type="line", x0=prices[0], x1=prices[-1], y0=0, y1=0,
                  line=dict(color="gray", width=1, dash="dash"), yref="y2")

    # Current spot marker
    fig.add_vline(x=s0, line_dash="dash", line_color="#333333", line_width=1,
                  annotation_text=f"Spot ₹{s0:,.0f}", annotation_position="top right")

    fig.update_layout(
        title="Strategy Payoff at Expiry — Individual Legs vs Net P&L",
        xaxis=dict(title="Spot Price at Expiry (₹)", tickformat=",.0f",
                   showgrid=True, gridcolor="#e9ecef"),
        # Left axis: individual legs (large scale)
        yaxis=dict(
            title="Individual Leg P&L (₹)",
            tickformat=",.0f",
            showgrid=False,
            titlefont=dict(color="#555555"),
            tickfont=dict(color="#555555"),
        ),
        # Right axis: net P&L (zoomed in so it's clearly visible)
        yaxis2=dict(
            title="Net P&L (₹)",
            tickformat=",.0f",
            overlaying="y",
            side="right",
            range=[-net_range_pad, net_range_pad],
            titlefont=dict(color=signal_color),
            tickfont=dict(color=signal_color),
            showgrid=True,
            gridcolor="#e9ecef",
            zeroline=True,
            zerolinecolor="gray",
        ),
        height=360,
        margin=dict(t=45, b=40, l=10, r=10),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
        plot_bgcolor="#f8f9fa",
        paper_bgcolor="white",
    )

    st.plotly_chart(fig, use_container_width=True)
    st.caption(
        "📌 *Dotted lines* = individual legs (left axis, large scale). "
        f"*Solid {signal_color} line* = Net P&L after friction (right axis, zoomed). "
        "Net P&L is flat because arbitrage payoff is locked regardless of expiry price."
    )

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
        # Long spot: profit when ST > S0
        s_leg = (st_price - s0) * total_units
        # Long put: pays (K - ST) if ST < K, costs premium always
        p_leg = (max(strike - st_price, 0) - p_mkt) * total_units
        # Short call: keeps premium, pays out (ST - K) if ST > K
        c_leg = (c_mkt - max(st_price - strike, 0)) * total_units

    elif signal_type == "reversal":
        # Short spot: profit when ST < S0
        s_leg = (s0 - st_price) * total_units
        # Short put: keeps premium, pays out (K - ST) if ST < K
        # At expiry: short put P&L = P_premium - max(K - ST, 0)
        p_leg = (p_mkt - max(strike - st_price, 0)) * total_units
        # Long call: pays premium, receives (ST - K) if ST > K
        # At expiry: long call P&L = max(ST - K, 0) - C_premium
        c_leg = (max(st_price - strike, 0) - c_mkt) * total_units

    else:
        s_leg = p_leg = c_leg = 0.0

    gross = s_leg + p_leg + c_leg
    # gross should equal spread_per_unit * total_units (locked)
    # Net = gross - friction (same across all scenarios = Net Profit)
    net = gross - total_friction

    rows.append({
        "Scenario":      label,
        "Expiry Price":  f"₹{st_price:,.0f}",
        "Spot Leg (₹)":  f"₹{s_leg:,.2f}",
        "Put Leg (₹)":   f"₹{p_leg:,.2f}",
        "Call Leg (₹)":  f"₹{c_leg:,.2f}",
        "Gross P&L (₹)": f"₹{gross:,.2f}",
        "Friction (₹)":  f"−₹{total_friction:,.2f}",
        "Net P&L (₹)":   f"₹{net:,.2f}",
    })

scenario_df = pd.DataFrame(rows)
st.dataframe(scenario_df, hide_index=True, use_container_width=True)

# Explain the key insight
gross_check = abs(spread_per_unit) * total_units
st.info(
    f"*Why is Net P&L the same in every row?* — This is the core proof of arbitrage. "
    f"No matter where the stock expires, the three legs (spot + put + call) always net to "
    f"the same locked gross spread of *₹{gross_check:,.2f}*. "
    f"After subtracting fixed friction of *₹{total_friction:,.2f}*, "
    f"you always get *₹{net_pnl:,.2f}* — identical to 'Net Profit' above. "
    f"The individual legs move wildly but perfectly offset each other — that's put-call parity at work."
)

# ─────────────────────────────────────────────────────────────────────────────
# 12. SENSITIVITY: HOW MANY LOTS TO BREAK EVEN?
# ─────────────────────────────────────────────────────────────────────────────
if signal_type != "none" and abs
