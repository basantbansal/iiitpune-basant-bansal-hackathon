import sys
import os

# Ensure the root project directory is on sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from src.engine.risk_engine import RiskEngine
from src.rebalancer.index_rebalancer import IndexRebalancer
from src.engine.ingestion import MarketNewsIngestion
from src.storage.db import SignalDatabase

import sys
import os
from dotenv import load_dotenv

# Load environment variables from .egroq_api_keynv file
load_dotenv()

# Page configuration
st.set_page_config(
    page_title="Tactical Index Rebalancer | Risk Management",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize engines & DB in session state for persistence
@st.cache_resource
def get_core_systems():
    return RiskEngine(), MarketNewsIngestion(), SignalDatabase()

risk_engine, ingestor, db = get_core_systems()

if "rebalancer" not in st.session_state:
    st.session_state.rebalancer = IndexRebalancer()
if "signals_log" not in st.session_state:
    st.session_state.signals_log = []
if "latest_orders" not in st.session_state:
    st.session_state.latest_orders = pd.DataFrame()

rebalancer = st.session_state.rebalancer

# --- Sidebar Controls ---
st.sidebar.header("System Configuration")
data_mode = st.sidebar.radio("Data Source Mode", ["Live Market (Google RSS)", "Offline Crisis Replay"])
env_groq_key = os.getenv("GROQ_API_KEY", "")

groq_api_key = st.sidebar.text_input(
    "Groq API Key (Optional Hybrid LLM)", 
    type="password", 
    value=env_groq_key  # <--- This automatically fills the password box
)


st.sidebar.markdown("---")
st.sidebar.header("Portfolio Parameters")
initial_capital = st.sidebar.number_input("Assets Under Management (AUM)", value=1_000_000, step=100_000)
alpha_tilt = st.sidebar.slider("Active Risk Tolerance (alpha)", min_value=0.01, max_value=0.10, value=0.05, step=0.01)
rebalancer.alpha_tilt = alpha_tilt

# Bulletproof DB Flush: Physically deletes the file and rebuilds it
if st.sidebar.button("🗑️ Flush DB & Reset State"):
    if os.path.exists(db.db_path):
        try:
            os.remove(db.db_path)
        except Exception:
            pass
    db._init_db() # Rebuild the empty table
    st.session_state.rebalancer = IndexRebalancer(initial_capital=initial_capital, alpha_tilt=alpha_tilt)
    st.session_state.signals_log = []
    st.session_state.latest_orders = pd.DataFrame()
    st.rerun()

# --- Main Header ---
st.title("Tactical Index Rebalancer (Module A)")
st.caption("Quantitative Risk Signal Extraction, Deduplication, & Dynamic Portfolio Reallocation")
st.markdown("---")

# Calculate Top KPIs safely
current_prices = rebalancer.fetch_current_prices()
total_val = sum(rebalancer.current_shares[t] * current_prices[t] for t in rebalancer.tickers)

# Safely extract min/max weights for display
current_weights_series = pd.Series(rebalancer.current_weights)
max_asset = current_weights_series.idxmax()
min_asset = current_weights_series.idxmin()
max_wt = current_weights_series[max_asset] * 100
min_wt = current_weights_series[min_asset] * 100

kpi1, kpi2, kpi3, kpi4 = st.columns(4)
kpi1.metric("Current AUM", f"${total_val:,.2f}")
kpi2.metric("Max Overweight Asset", f"{max_asset} ({max_wt:.2f}%)")
kpi3.metric("Max Underweight Asset", f"{min_asset} ({min_wt:.2f}%)")

if not st.session_state.latest_orders.empty:
    total_turnover = st.session_state.latest_orders["Trade Value ($)"].sum()
    kpi4.metric("Capital Reallocated", f"${total_turnover:,.2f}")
else:
    kpi4.metric("Capital Reallocated", "$0.00")

# --- Execution Button ---
st.markdown("### ") # Spacing
execute_live = st.button("🚀 Fetch News & Update Weights", type="primary", use_container_width=True)

if execute_live:
    with st.spinner("Fetching news, checking DB for duplicates, and scoring via Risk Engine..."):
        # Force offline mode if selected
        if "Offline" in data_mode:
            raw_news = ingestor.fetch_live_news(max_items_per_ticker=0)
        else:
            raw_news = ingestor.fetch_live_news(max_items_per_ticker=1)
            
        new_signals_processed = []
        
        for item in raw_news:
            article_hash = db.generate_hash(item["headline"], item["ticker"])
            
            if not db.is_article_processed(article_hash):
                sig = risk_engine.analyze(
                    text=item["headline"], 
                    entity=item["ticker"],
                    groq_api_key=groq_api_key if groq_api_key else None
                )
                sig_dict = sig.to_dict()
                
                db.log_signal(
                    article_hash=article_hash,
                    signal_dict=sig_dict,
                    headline=item["headline"],
                    source=item["source"],
                    published_at=item["published_at"]
                )
                
                new_signals_processed.append(sig_dict)

    if new_signals_processed:
        st.success(f"Processed {len(new_signals_processed)} new actionable market events.")
        st.session_state.signals_log.extend(new_signals_processed)
        st.session_state.latest_orders = rebalancer.rebalance(new_signals_processed)
        st.rerun()
    else:
        st.info("✅ All recent headlines have already been processed and priced into the portfolio. No new active risk detected.")

st.markdown("---")

# --- Section 1: Risk Radar (Signals) ---
st.subheader("📡 Risk Radar (Auditable Signals)")
if st.session_state.signals_log:
    sig_df = pd.DataFrame(st.session_state.signals_log)[
        ["entity", "event_classification", "sentiment_score", "impact_score", "confidence", "model_version", "headline"]
    ]
    sig_df.columns = ["Ticker", "Event Type", "Sentiment", "Impact", "Confidence", "Model Engine", "Source Text"]
    st.dataframe(sig_df, use_container_width=True, hide_index=True)
else:
    st.write("Awaiting live signals. The portfolio is currently operating on baseline neutral data.")

st.markdown("---")

# --- Section 2: Algorithmic Rebalancer Execution ---
st.subheader("⚖️ Algorithmic Rebalancer Execution")

col_chart, col_table = st.columns([1, 1.5])

if not st.session_state.latest_orders.empty:
    orders_df = st.session_state.latest_orders
    
    with col_chart:
        st.markdown("**Allocation Variance (Benchmark vs Target)**")
        chart_data = pd.DataFrame({
            "Ticker": orders_df["Ticker"],
            "Previous": orders_df["Prev Weight"].apply(lambda x: float(x.replace("%", ""))),
            "Target": orders_df["New Weight"].apply(lambda x: float(x.replace("%", ""))),
        })
        
        fig = go.Figure()
        fig.add_trace(go.Bar(
            name='Previous Weight', 
            x=chart_data['Ticker'], 
            y=chart_data['Previous'], 
            marker_color='#475569',
            text=chart_data['Previous'].apply(lambda x: f"{x}%"),
            textposition='auto'
        ))
        fig.add_trace(go.Bar(
            name='Target Weight', 
            x=chart_data['Ticker'], 
            y=chart_data['Target'], 
            marker_color='#3b82f6',
            text=chart_data['Target'].apply(lambda x: f"{x}%"),
            textposition='auto'
        ))
        fig.update_layout(
            barmode='group', 
            plot_bgcolor='rgba(0,0,0,0)', 
            paper_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=30, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            yaxis=dict(title="Weight (%)", gridcolor="#333333"),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_table:
        st.markdown("**Trade Execution Ticket**")
        st.dataframe(orders_df, use_container_width=True, hide_index=True)

else:
    with col_chart:
        st.markdown("**Target Allocation (Baseline)**")
        base_weights = [10.0] * len(rebalancer.tickers)
        fig = go.Figure(data=[
            go.Bar(
                x=rebalancer.tickers, 
                y=base_weights, 
                marker_color='#475569',
                text=[f"{w}%" for w in base_weights],
                textposition='auto'
            )
        ])
        fig.update_layout(
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=30, b=0),
            yaxis=dict(title="Weight (%)", gridcolor="#333333", range=[0, 30]),
        )
        st.plotly_chart(fig, use_container_width=True)
        
    with col_table:
        st.markdown("**Baseline Portfolio (Equal Weight)**")
        base_df = pd.DataFrame([
            {"Ticker": t, "Target Weight": "10.00%", "Current Shares": round(rebalancer.current_shares[t], 2)} 
            for t in rebalancer.tickers
        ])
        st.dataframe(base_df, use_container_width=True, hide_index=True)