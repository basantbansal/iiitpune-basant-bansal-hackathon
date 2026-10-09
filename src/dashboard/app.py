import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), ".")))
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from src.engine.risk_engine import RiskEngine
from src.rebalancer.index_rebalancer import IndexRebalancer
from src.engine.ingestion import MarketNewsIngestion
from src.storage.db import SignalDatabase
from src.engine.processor import EntityResolver, SemanticDedup
from src.engine.stress_engine import StressEngine
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_title="Institutional Risk Terminal",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for premium terminal look
st.markdown("""
<style>
    /* Dark professional theme overrides */
    .stApp {
        background-color: #0E1117;
        color: #C9D1D9;
    }
    h1, h2, h3 {
        color: #E6EDF3 !important;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }
    .stMetric {
        background-color: #161B22;
        border: 1px solid #30363D;
        border-radius: 6px;
        padding: 15px;
    }
    .stMetric label {
        color: #8B949E !important;
    }
    .stDataFrame {
        border: 1px solid #30363D;
        border-radius: 6px;
    }
    div.block-container {
        padding-top: 2rem;
    }
</style>
""", unsafe_allow_html=True)

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
if "last_updated" not in st.session_state:
    st.session_state.last_updated = "Never"

rebalancer = st.session_state.rebalancer

# Sidebar
with st.sidebar:
    st.title("⚙️ System Control")
    st.markdown("---")
    
    data_mode = st.radio("Data Feed", ["Live Market (Google RSS)", "Offline Crisis Replay"])
    
    groq_api_key = os.getenv("GROQ_API_KEY", "")
    if groq_api_key:
        st.success("LLM Engine: Active")
    else:
        st.warning("LLM Engine: Fallback Mode")
        
    st.markdown("---")
    st.subheader("Portfolio Parameters")
    initial_capital = st.number_input("AUM ($)", value=1_000_000, step=100_000, format="%d")
    alpha_tilt = st.slider("Active Risk Tolerance (α)", min_value=0.01, max_value=0.10, value=0.05, step=0.01)
    rebalancer.alpha_tilt = alpha_tilt
    
    st.markdown("---")
    if st.button("🗑️ Reset Portfolio State", use_container_width=True):
        if os.path.exists(db.db_path):
            try: os.remove(db.db_path)
            except Exception: pass
        db._init_db()
        st.session_state.rebalancer = IndexRebalancer(initial_capital=initial_capital, alpha_tilt=alpha_tilt)
        st.session_state.signals_log = []
        st.session_state.latest_orders = pd.DataFrame()
        st.session_state.last_updated = "Never"
        st.rerun()

st.title("Global Equity Risk Terminal")
st.caption(f"Last updated: {st.session_state.last_updated} UTC | Real-time NLP Risk Assessment")

# Compute top-level metrics
current_prices = rebalancer.fetch_current_prices()
total_val = sum(rebalancer.current_shares[t] * current_prices[t] for t in rebalancer.tickers)
cw_series = pd.Series(rebalancer.current_weights)
max_asset, min_asset = cw_series.idxmax(), cw_series.idxmin()
total_turnover = st.session_state.latest_orders["Trade Value ($)"].sum() if not st.session_state.latest_orders.empty else 0.0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Total AUM", f"${total_val:,.0f}")
col2.metric("Highest Conviction", f"{max_asset}", f"{cw_series[max_asset]*100:.1f}% wt")
col3.metric("Lowest Conviction", f"{min_asset}", f"{cw_series[min_asset]*100:.1f}% wt")
col4.metric("Capital Reallocated", f"${total_turnover:,.0f}")

st.markdown("---")

# Main Action
col_action, col_info = st.columns([1, 3])
with col_action:
    if st.button("🔄 Execute Market Scan", type="primary", use_container_width=True):
        with st.spinner("Aggregating market news & computing signal impacts..."):
            raw_news = ingestor.fetch_live_news(max_items_per_ticker=0 if "Offline" in data_mode else 1)
            new_signals = []
            dedup_engine = SemanticDedup(time_window_hours=24)
            recent_docs = db.get_recent_documents(hours=24)
            batch_hashes = set()
            
            for item in raw_news:
                raw_hd = item["headline"]
                norm_hd = EntityResolver.normalize_text(raw_hd)
                d_hash = SemanticDedup.get_document_hash(norm_hd)
                if d_hash in batch_hashes: continue
                batch_hashes.add(d_hash)
                
                resolved = EntityResolver.resolve_entities(raw_hd)
                entities = {r.ticker for r in resolved}
                dedup_res = dedup_engine.check_duplicate(norm_hd, entities, recent_docs)
                
                doc_data = {
                    "document_hash": d_hash, "canonical_group_id": dedup_res["canonical_group_id"],
                    "headline": raw_hd, "normalized_headline": norm_hd,
                    "source": item["source"], "published_at": item["published_at"],
                    "is_duplicate": dedup_res["is_duplicate"], "duplicate_reason": dedup_res["reason"],
                    "resolved_entities": list(entities)
                }
                db.log_document(doc_data)
                recent_docs.insert(0, doc_data)
                
                if not dedup_res["is_duplicate"]:
                    for ent in entities:
                        a_hash = db.generate_hash(raw_hd, ent)
                        if not db.is_article_processed(a_hash):
                            sig = risk_engine.analyze(text=raw_hd, entity=ent)
                            sig_dict = sig.to_dict()
                            db.log_signal(
                                article_hash=a_hash, signal_dict=sig_dict,
                                headline=raw_hd, source=item["source"],
                                published_at=item["published_at"], document_hash=d_hash
                            )
                            new_signals.append(sig_dict)
            
            if new_signals:
                st.session_state.signals_log.extend(new_signals)
                st.session_state.latest_orders = rebalancer.rebalance(new_signals)
                st.session_state.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.rerun()
            else:
                st.info("No actionable new risk events detected in the current window.")

# Tabs for Organization
tab1, tab2, tab3 = st.tabs(["📊 Portfolio Allocation", "📡 Active Risk Signals", "⚠️ Macro Stress Testing"])

with tab1:
    col_chart, col_table = st.columns([1.2, 1])
    with col_chart:
        st.markdown("#### Target vs. Baseline Weight Distribution")
        df_wts = pd.DataFrame([
            {"Ticker": t, "Target": rebalancer.current_weights[t]*100, "Baseline": 10.0} 
            for t in rebalancer.tickers
        ])
        fig = go.Figure()
        fig.add_trace(go.Bar(name='Target', x=df_wts['Ticker'], y=df_wts['Target'], marker_color='#3b82f6'))
        fig.add_trace(go.Bar(name='Baseline', x=df_wts['Ticker'], y=df_wts['Baseline'], marker_color='#475569'))
        fig.update_layout(
            barmode='group', plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
            margin=dict(l=0, r=0, t=10, b=0), yaxis=dict(title="Weight (%)", gridcolor="#333333"),
            font=dict(color="#C9D1D9"), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )
        st.plotly_chart(fig, use_container_width=True)
        
    with col_table:
        st.markdown("#### Execution Ledger")
        if not st.session_state.latest_orders.empty:
            st.dataframe(st.session_state.latest_orders, use_container_width=True, hide_index=True)
        else:
            st.write("No active rebalancing orders pending.")

with tab2:
    if st.session_state.signals_log:
        sig_df = pd.DataFrame(st.session_state.signals_log)[
            ["entity", "event_classification", "sentiment_score", "impact_score", "confidence", "model_version", "headline"]
        ].sort_values("impact_score", ascending=False)
        sig_df.columns = ["Asset", "Event", "Sentiment", "Impact", "Confidence", "Model", "Headline"]
        
        # Color code sentiment
        def color_sentiment(val):
            color = '#2ea043' if val > 0 else '#da3633' if val < 0 else '#8b949e'
            return f'color: {color}'
            
        st.dataframe(sig_df.style.map(color_sentiment, subset=['Sentiment']), use_container_width=True, hide_index=True)
    else:
        st.info("Awaiting live signals. Portfolio operating on baseline.")

with tab3:
    st.markdown("#### Scenario Analysis & Tail Risk")
    col_scen, col_res = st.columns([1, 2])
    with col_scen:
        scen_name = st.radio("Select Macro Shock Scenario", list(stress_engine.scenarios.keys()))
        shock = stress_engine.scenarios[scen_name]
        st.info(shock["desc"])
        st.write(f"**Equities:** {shock['equity_shock']*100}% | **Rates:** {shock['rate_shock_bps']} bps | **Spreads:** {shock['spread_shock_bps']} bps")
        run_stress = st.button("Run Simulation", use_container_width=True)
        
    with col_res:
        if run_stress:
            out = stress_engine.run_scenario(rebalancer.current_weights, total_val, scen_name)
            df_stress = out["market_df"]
            t_loss = df_stress["Total P&L"].sum()
            
            st.metric("Estimated Portfolio Drawdown", f"${t_loss:,.0f}", f"{(t_loss/total_val)*100:.2f}%")
            
            fig_stress = go.Figure(go.Bar(
                x=df_stress["Ticker"], y=df_stress["Drawdown (%)"],
                marker_color=['#da3633' if x < 0 else '#2ea043' for x in df_stress["Drawdown (%)"]]
            ))
            fig_stress.update_layout(
                title="Asset-Level Drawdown (%)",
                plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', margin=dict(l=0, r=0, t=30, b=0),
                yaxis_title="%", font=dict(color="#C9D1D9")
            )
            st.plotly_chart(fig_stress, use_container_width=True)

