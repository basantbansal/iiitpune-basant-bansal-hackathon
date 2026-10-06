import sys
import os

# Ensure the root project directory is on sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import streamlit as st
import pandas as pd

from src.engine.risk_engine import RiskEngine
from src.rebalancer.index_rebalancer import IndexRebalancer

# Page configuration
st.set_page_config(
    page_title="Tactical Index Rebalancer | Risk Management",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize engines in session state for persistence
@st.cache_resource
def get_risk_engine():
    return RiskEngine()

if "rebalancer" not in st.session_state:
    st.session_state.rebalancer = IndexRebalancer()

risk_engine = get_risk_engine()
rebalancer = st.session_state.rebalancer

# Header
st.title("Tactical Index Rebalancer (Module A)")
st.caption("Quantitative Risk Signal Extraction & Dynamic Portfolio Reallocation")
st.markdown("---")

# Sidebar: Institutional Controls
st.sidebar.header("Portfolio Parameters")

initial_capital = st.sidebar.number_input(
    "Assets Under Management (AUM)", value=1_000_000, step=100_000
)
alpha_tilt = st.sidebar.slider(
    "Active Risk Tolerance (alpha)",
    min_value=0.01,
    max_value=0.10,
    value=0.05,
    step=0.01,
)
rebalancer.alpha_tilt = alpha_tilt

st.sidebar.markdown("---")
st.sidebar.subheader("Stress Scenarios")

scenarios = {
    "Select a market event...": [],
    "Scenario A: Sovereign Credit Contagion": [
        ("TSLA", "Moody's downgrades sovereign automotive debt rating amid imminent bond default concerns for Tesla."),
        ("XOM", "Global supply chain disruption triggers acute macroeconomic inflation warnings."),
    ],
    "Scenario B: Idiosyncratic Tech Alpha": [
        ("NVDA", "Nvidia announces breakthrough next-generation Blackwell AI chip architecture with surging enterprise demand."),
        ("MSFT", "Microsoft cloud beats quarterly revenue estimates with record corporate adoption."),
    ],
    "Scenario C: Regulatory Shock": [
        ("META", "Federal trade commission launches severe antitrust and fraud probe into Meta data practices."),
        ("GOOGL", "European Union imposes record tariff and regulatory sanctions on Alphabet search dominance."),
    ],
}

selected_scenario = st.sidebar.selectbox("Load Pre-Packaged Event", list(scenarios.keys()))

if st.sidebar.button("Reset to Target Benchmark"):
    st.session_state.rebalancer = IndexRebalancer(
        initial_capital=initial_capital, alpha_tilt=alpha_tilt
    )
    st.rerun()

# Section 1: Signal Provenance
st.subheader("Signal Provenance & NLP Extraction")

input_items = []

if selected_scenario != "Select a market event...":
    input_items = scenarios[selected_scenario]
else:
    with st.expander("Manual Event Ingestion", expanded=True):
        col_t, col_h = st.columns([1, 4])
        with col_t:
            custom_ticker = st.selectbox("Target Ticker", rebalancer.tickers, index=2)
        with col_h:
            custom_headline = st.text_input(
                "Source Text",
                value="Nvidia posts record quarterly profits, beating revenue guidance by 24%.",
            )
        if st.button("Execute Extraction"):
            input_items = [(custom_ticker, custom_headline)]

if input_items:
    parsed_signals = []
    for ticker, text in input_items:
        sig = risk_engine.analyze(text, entity=ticker)
        parsed_signals.append(sig.to_dict())

    # Format Signals Dataframe
    sig_df = pd.DataFrame(parsed_signals)[
        [
            "entity",
            "event_classification",
            "sentiment_score",
            "impact_score",
            "confidence",
            "evidence_span",
            "headline",
        ]
    ]
    sig_df.columns = [
        "Ticker",
        "Event Type",
        "Sentiment",
        "Impact",
        "Confidence",
        "Extracted Evidence",
        "Source Text",
    ]

    st.dataframe(sig_df, use_container_width=True, hide_index=True)

    # Section 2: Rebalancer Execution
    st.markdown("---")
    st.subheader("Algorithmic Rebalancer Execution")

    with st.spinner("Fetching market data and computing simplex projection..."):
        orders_df = rebalancer.rebalance(parsed_signals)

    # Key Performance Indicators
    total_val = sum(
        rebalancer.current_shares[t] * rebalancer.fetch_current_prices()[t]
        for t in rebalancer.tickers
    )

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("Current AUM", f"${total_val:,.2f}")
    kpi2.metric(
        "Max Overweight Asset",
        f"{orders_df.iloc[0]['Ticker']} ({orders_df.iloc[0]['New Weight']})",
    )
    kpi3.metric(
        "Max Underweight Asset",
        f"{orders_df.iloc[-1]['Ticker']} ({orders_df.iloc[-1]['New Weight']})",
    )
    total_turnover = orders_df["Trade Value ($)"].sum()
    kpi4.metric("Capital Reallocated", f"${total_turnover:,.2f}")

    col_chart, col_table = st.columns([1, 2])

    with col_chart:
        st.markdown("**Allocation Variance (Benchmark vs Target)**")
        chart_data = pd.DataFrame(
            {
                "Ticker": orders_df["Ticker"],
                "Previous Weight": orders_df["Prev Weight"].apply(lambda x: float(x.replace("%", ""))),
                "Target Weight": orders_df["New Weight"].apply(lambda x: float(x.replace("%", ""))),
            }
        ).set_index("Ticker")
        st.bar_chart(chart_data)

    with col_table:
        st.markdown("**Trade Execution Ticket**")
        st.dataframe(orders_df, use_container_width=True, hide_index=True)

else:
    st.info("Awaiting input data. Select a scenario from the parameters menu or ingest a manual event.")