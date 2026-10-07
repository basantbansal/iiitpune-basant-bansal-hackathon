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

from src.engine.stress_engine import StressEngine

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
    return RiskEngine(), MarketNewsIngestion(), SignalDatabase(), StressEngine()

risk_engine, ingestor, db, stress_engine = get_core_systems()

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

# --- Section 3: Strategic Stress Testing (Module B) --- 

st.markdown("---")

# --- Section 3: Strategic Stress Testing (Module B) ---
st.subheader("⚠️ Strategic Stress Testing (Module B)")
st.caption("Evaluate portfolio resilience against historical and synthetic macroeconomic shocks.")

col_scen, col_res = st.columns([1, 2.5])

with col_scen:
    selected_scenario = st.radio("Select Macroeconomic Scenario", list(stress_engine.scenarios.keys()))
    shock_params = stress_engine.scenarios[selected_scenario]
    
    st.markdown("#### Shock Parameters")
    st.info(shock_params["desc"])
    st.metric("Broad Equity Market", f"{shock_params['equity_shock']*100}%")
    st.metric("Interest Rates (DV01)", f"{shock_params['rate_shock_bps']:+} bps")
    st.metric("Credit Spreads", f"{shock_params['spread_shock_bps']:+} bps")
    
    run_stress = st.button("🔥 Run Stress Test", type="primary", use_container_width=True)

with col_res:
    if run_stress:
        with st.spinner("Calculating cross-asset sensitivities..."):
            stress_df = stress_engine.run_scenario(
                current_weights=rebalancer.current_weights, 
                total_aum=total_val,  # Using total_val calculated earlier in the script
                scenario_name=selected_scenario
            )
            
            total_loss = stress_df["Total P&L"].sum()
            portfolio_drawdown = (total_loss / total_val) * 100
            
            # Top-level stress KPIs
            sk1, sk2, sk3 = st.columns(3)
            sk1.metric("Pre-Shock AUM", f"${total_val:,.0f}")
            sk2.metric("Stressed AUM", f"${(total_val + total_loss):,.0f}", f"{total_loss:,.0f}")
            sk3.metric("Portfolio Drawdown", f"{portfolio_drawdown:.2f}%")
            
            st.markdown("#### Asset-Level Exposure & P&L Attribution")
            
            # Format for display
            display_df = stress_df.copy()
            format_cols = ["Base Exposure", "Equity P&L", "Rate P&L", "Spread P&L", "Total P&L", "Stressed Value"]
            for c in format_cols:
                display_df[c] = display_df[c].apply(lambda x: f"${x:,.0f}")
            display_df["Drawdown (%)"] = display_df["Drawdown (%)"].apply(lambda x: f"{x:.2f}%")
            
            st.dataframe(display_df, use_container_width=True, hide_index=True)
            
            # Visualize Drawdown Contribution
            st.markdown("#### Drawdown Contribution by Asset")
            fig_stress = go.Figure(go.Bar(
                x=stress_df["Ticker"],
                y=stress_df["Drawdown (%)"],
                marker_color=['#ef4444' if x < 0 else '#22c55e' for x in stress_df["Drawdown (%)"]]
            ))
            fig_stress.update_layout(
                plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                margin=dict(l=0, r=0, t=10, b=0), yaxis_title="Asset Drawdown (%)",
                font=dict(color="white")
            )
            st.plotly_chart(fig_stress, use_container_width=True)
    else:
        st.write("Select a scenario on the left and click 'Run Stress Test' to evaluate the current portfolio.")