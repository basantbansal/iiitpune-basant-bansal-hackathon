import os
import uuid
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime

from src.engine.risk_engine import RiskEngine
from src.rebalancer.index_rebalancer import IndexRebalancer
from src.engine.ingestion import MarketNewsIngestion
from src.storage.db import SignalDatabase
from src.engine.processor import EntityResolver, SemanticDedup
from src.stress_testing.stress_engine import StressEngine
from dotenv import load_dotenv
import src.dashboard.stock_detail as stock_detail

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

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_portfolio_covariance(tickers):
    import yfinance as yf
    import numpy as np
    try:
        data = yf.download(tickers, period="1y", interval="1d", auto_adjust=True, progress=False)
        if "Close" in data.columns:
            prices = data["Close"]
        else:
            prices = data
        returns = prices.pct_change().dropna()
        # Ensure the columns match the order of tickers provided
        returns = returns[tickers]
        cov_matrix = returns.cov() * 252
        return cov_matrix
    except Exception as e:
        return None

def calculate_portfolio_volatility(weights_dict, cov_matrix, tickers):
    import numpy as np
    w = np.array([weights_dict.get(t, 0.0) for t in tickers])
    var = np.dot(w.T, np.dot(cov_matrix, w))
    return np.sqrt(var) * 100 # return as percentage

def get_core_systems():
    return RiskEngine(), MarketNewsIngestion(), SignalDatabase(), StressEngine()

risk_engine, ingestor, db, stress_engine = get_core_systems()

if "session_initialized" not in st.session_state:
    st.session_state.session_initialized = True
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.rebalancer = IndexRebalancer()
    st.session_state.signals_log = []
    st.session_state.latest_orders = pd.DataFrame()
    st.session_state.last_updated = "Never"
    st.session_state.auto_trigger_stress = None

rebalancer = st.session_state.rebalancer

# Sidebar
with st.sidebar:
    st.title("⚙️ System Control")
    st.markdown("---")

    data_mode = st.radio("Data Feed", ["Live Market (Google RSS)", "Offline Crisis Replay"], help="Offline Replay uses bundled deterministic demonstration data. The database persistently records an audit trail; prior replays will bypass re-processing.")

    groq_api_key = os.getenv("GROQ_API_KEY", "")
    if groq_api_key:
        st.success("LLM API: Configured")
    else:
        st.warning("LLM Engine: Fallback Mode")

    st.markdown("---")
    st.subheader("Portfolio Parameters")
    initial_capital = st.number_input("Portfolio Value ($)", value=1_000_000, step=100_000, format="%d")

    alpha_tilt = st.slider("Active Risk Tolerance (α)", min_value=0.01, max_value=0.10, value=0.05, step=0.01)
    rebalancer.alpha_tilt = alpha_tilt
    st.markdown("---")
    st.subheader("Live Feed Options")
    max_items = st.slider("Max Articles Per Company", min_value=1, max_value=10, value=3)

st.title("Global Equity Risk Terminal")
st.caption(f"Last updated: {st.session_state.last_updated} UTC | Real-time NLP Risk Assessment")

# Compute top-level metrics
current_prices = rebalancer.fetch_current_prices()
total_val = sum(rebalancer.current_shares[t] * current_prices[t] for t in rebalancer.tickers)
cw_series = pd.Series(rebalancer.current_weights)
max_asset, min_asset = cw_series.idxmax(), cw_series.idxmin()
total_turnover = st.session_state.latest_orders["Trade Value ($)"].sum() if not st.session_state.latest_orders.empty else 0.0

col1, col2, col3, col4 = st.columns(4)
col1.metric("Portfolio Value", f"${total_val:,.0f}", help="Total Current Portfolio Value (Mark-to-Market)")
col2.metric("Largest Target Allocation", f"{max_asset}", f"{cw_series[max_asset]*100:.1f}% wt", help="Asset with the highest active target weight")
col3.metric("Total value traded to rebalance", f"${total_turnover:,.0f}", help="Gross turnover (absolute total dollar value of all shares bought and sold to reach new targets)")
cost_bps = 10.0
est_txn_cost = total_turnover * (cost_bps / 10000.0)
col4.metric("Estimated Trading Costs", f"${est_txn_cost:,.0f}", help=f"Estimated transaction costs at {cost_bps} basis points of total value traded")

st.markdown("---")

# Main Action
col_action, col_info = st.columns([1, 3])
with col_action:
    if st.button("🔄 Execute Market Scan", type="primary", use_container_width=True):
        with st.spinner("Aggregating market news & computing signal impacts..."):
            raw_news = ingestor.fetch_live_news(max_items_per_ticker=max_items, force_fallback=("Offline" in data_mode), max_total=25)

            if not raw_news and "Offline" not in data_mode:
                st.warning("Live Market feed returned no new articles or the connection failed. You can switch to 'Offline Crisis Replay' in the sidebar to run a deterministic simulation.")

            new_signals = []
            dedup_engine = SemanticDedup(time_window_hours=24)
            recent_docs = db.get_recent_documents(hours=24)
            batch_hashes = set()

            is_offline = "Offline" in data_mode
            offline_run_id = str(uuid.uuid4())[:8] if is_offline else ""
            stats_retrieved = len(raw_news)
            stats_skipped = 0
            stats_no_entities = 0
            stats_processed = 0

            for item in raw_news:
                raw_hd = item["headline"]
                norm_hd = EntityResolver.normalize_text(raw_hd)

                if is_offline:
                    d_hash = f"replay-{offline_run_id}-{SemanticDedup.get_document_hash(norm_hd)}"
                else:
                    d_hash = SemanticDedup.get_document_hash(norm_hd)

                if d_hash in batch_hashes: continue
                batch_hashes.add(d_hash)

                resolved = EntityResolver.resolve_entities(raw_hd)
                entities = {r.ticker for r in resolved}

                if is_offline:
                    dedup_res = {"is_duplicate": False, "canonical_group_id": d_hash, "reason": None}
                else:
                    dedup_res = dedup_engine.check_duplicate(norm_hd, entities, recent_docs)

                doc_data = {
                    "document_hash": d_hash, "canonical_group_id": dedup_res["canonical_group_id"],
                    "headline": raw_hd, "normalized_headline": norm_hd,
                    "source": item.get("source", "News"), "published_at": item["published_at"],
                    "is_duplicate": dedup_res["is_duplicate"], "duplicate_reason": dedup_res["reason"],
                    "resolved_entities": list(entities)
                }
                db.log_document(doc_data)

                if not is_offline:
                    recent_docs.insert(0, doc_data)

                if dedup_res["is_duplicate"]:
                    stats_skipped += 1
                else:
                    if not entities:
                        stats_no_entities += 1
                    else:
                        processed_any = False
                        for ent in entities:
                            if is_offline:
                                a_hash = f"replay-{offline_run_id}-{db.generate_hash(raw_hd, ent)}"
                            else:
                                a_hash = db.generate_hash(raw_hd, ent)

                            if not db.is_article_processed(a_hash):
                                processed_any = True
                                sig = risk_engine.analyze(text=raw_hd, entity=ent, source=item.get("source", "News"))
                                sig_dict = sig.to_dict()
                                sig_dict["source"] = item.get("source", "News")
                                sig_dict["article_hash"] = a_hash
                                db.log_signal(
                                    article_hash=a_hash, signal_dict=sig_dict,
                                    headline=raw_hd, source=item.get("source", "News"),
                                    published_at=item["published_at"], document_hash=d_hash
                                )
                                new_signals.append(sig_dict)
                            else:
                                sig_dict = db.get_signal(a_hash)
                                if sig_dict:
                                    existing_hashes = {s.get("article_hash") for s in st.session_state.signals_log}
                                    if a_hash not in existing_hashes:
                                        processed_any = True
                                        new_signals.append(sig_dict)

                        if processed_any:
                            stats_processed += 1
                        else:
                            stats_skipped += 1


            if new_signals:
                if not is_offline and hasattr(ingestor, "coverage_stats"):
                    st.info(f"📰 **Live Feed Coverage:** Retrieved {stats_retrieved} articles. Companies with news: " + ", ".join([f"{k} ({v})" for k,v in ingestor.coverage_stats.items() if v > 0]) + " | No news: " + ", ".join([k for k,v in ingestor.coverage_stats.items() if v == 0]))

                st.session_state.signals_log.extend(new_signals)

                high_impact = [s for s in new_signals if s.get("impact_score", 0) > 7]
                if high_impact:
                    st.session_state.auto_trigger_stress = high_impact[0]
                else:
                    st.session_state.auto_trigger_stress = None

                try:
                    st.session_state.latest_orders = rebalancer.rebalance(new_signals)
                    st.session_state.last_updated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                except ValueError as e:
                    st.error(f"Rebalancing failed due to infeasible constraints: {str(e)}")
                st.rerun()
            else:
                if stats_retrieved == 0:
                    st.info("No articles retrieved from the feed.")
                elif stats_processed == 0 and stats_skipped > 0 and stats_no_entities == 0:
                    st.info(f"Retrieved {stats_retrieved} articles, but all were skipped (already processed).")
                elif stats_processed == 0 and stats_no_entities > 0 and stats_skipped == 0:
                    st.info(f"Retrieved {stats_retrieved} articles, but none contained monitored entities.")
                elif stats_processed == 0:
                    st.info(f"Retrieved {stats_retrieved} articles. {stats_skipped} skipped as duplicates, {stats_no_entities} unrelated to portfolio. No new signals generated.")
                else:
                    st.info("No actionable new risk events detected in the current window.")


if st.session_state.get("selected_stock"):
    if st.button("← Back to Portfolio"):
        st.session_state.selected_stock = None
        st.rerun()
    stock_detail.render_stock_detail(st.session_state.selected_stock, rebalancer, stress_engine, st.session_state.signals_log)
else:
    # Tabs for Organization
    tab1, tab2, tab3 = st.tabs(["📊 Portfolio Allocation", "📡 Active Risk Signals", "⚠️ Macro Stress Testing"])


    with tab1:
        col_chart, col_table = st.columns([1.2, 1])
        with col_chart:

            st.markdown("#### Target vs. Baseline Weight Distribution")

            # Calculate and display Portfolio Volatility Risk
            cov_matrix = fetch_portfolio_covariance(rebalancer.tickers)
            if cov_matrix is not None:
                baseline_weights = {t: 1.0/len(rebalancer.tickers) for t in rebalancer.tickers}
                baseline_vol = calculate_portfolio_volatility(baseline_weights, cov_matrix, rebalancer.tickers)
                target_vol = calculate_portfolio_volatility(rebalancer.current_weights, cov_matrix, rebalancer.tickers)

                v1, v2, v3 = st.columns(3)
                v1.metric("Baseline Volatility (Risk)", f"{baseline_vol:.2f}%", help="Annualized historical volatility of an equal-weight portfolio.")
                v2.metric("Target Volatility (Risk)", f"{target_vol:.2f}%", f"{target_vol - baseline_vol:+.2f}%", delta_color="inverse", help="Annualized historical volatility of the AI-rebalanced target portfolio. A negative delta indicates risk reduction.")


            df_wts = pd.DataFrame([
                {"Ticker": t, "Target": rebalancer.current_weights[t]*100, "Baseline": 100.0 / len(rebalancer.tickers)}
                for t in rebalancer.tickers
            ])
            fig = go.Figure()
            fig.add_trace(go.Bar(name='Target', x=df_wts['Ticker'], y=df_wts['Target'], marker_color='#3b82f6', text=df_wts['Target'].apply(lambda x: f"{x:.1f}%"), textposition='auto'))
            fig.add_trace(go.Bar(name='Baseline', x=df_wts['Ticker'], y=df_wts['Baseline'], marker_color='#475569', text=df_wts['Baseline'].apply(lambda x: f"{x:.1f}%"), textposition='auto'))
            fig.update_layout(
                barmode='group', plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)',
                margin=dict(l=0, r=0, t=10, b=0), yaxis=dict(title="Target Portfolio Weight (%)", gridcolor="#333333"),
                font=dict(color="#C9D1D9"), legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
            )
            st.plotly_chart(fig, use_container_width=True)
            st.info("💡 **How to read this:** The 'Baseline' is an equal-weight starting point. The 'Target' shows how the AI Rebalancer shifted weights—allocating more capital to positively trending assets and reducing exposure to negative risks.")

        with col_table:
            st.markdown("#### Execution Ledger")
            if not st.session_state.latest_orders.empty:
                event = st.dataframe(
                    st.session_state.latest_orders,
                use_container_width=True,
                hide_index=True,
                selection_mode="single-row",
                on_select="rerun"
            )
                if event and "selection" in event and event["selection"]["rows"]:
                    row_idx = event["selection"]["rows"][0]
                    ticker = st.session_state.latest_orders.iloc[row_idx]["Ticker"]
                    if st.session_state.get("selected_stock") != ticker:
                        st.session_state.selected_stock = ticker
                        st.rerun()
            else:
                st.write("No active rebalancing orders pending.")

    with tab2:
        if st.session_state.signals_log:
            sig_df = pd.DataFrame(st.session_state.signals_log)[
                ["entity", "event_classification", "sentiment_score", "impact_score", "confidence", "model_version", "source", "headline"]
            ].sort_values("impact_score", ascending=False)
            sig_df.columns = ["Asset", "Event", "Sentiment", "Impact", "Heuristic Score", "Model", "Source", "Headline"]

            # Format confidence
            sig_df["Heuristic Score"] = sig_df["Heuristic Score"].apply(lambda x: f"{x:.2f}")

            # Color code sentiment
            def color_sentiment(val):
                color = '#2ea043' if val > 0 else '#da3633' if val < 0 else '#8b949e'
                return f'color: {color}'

            st.dataframe(sig_df.style.map(color_sentiment, subset=['Sentiment']), use_container_width=True, hide_index=True)
            st.caption("Note: 'Heuristic Score' is not a statistically calibrated probability. It is a regex keyword match count on the deterministic path, or fixed to 0.90 for a successful LLM extraction.")
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
            auto_trigger = st.session_state.get("auto_trigger_stress")
            if auto_trigger:
                st.warning(f"⚠️ **Auto-Triggered Stress Test:** {auto_trigger['headline']} (Impact: {auto_trigger['impact_score']}) triggered a systemic risk evaluation.")

            if run_stress or auto_trigger:
                out = stress_engine.run_scenario(rebalancer.current_weights, total_val, scen_name)
                df_stress = out["market_df"]
                credit_metrics = out.get("credit_metrics", {})

                t_loss = df_stress["Total P&L"].sum()
                post_shock_val = total_val + t_loss

                # Display Equity Metrics
                st.markdown("##### 📈 Equity Index Portfolio")
                m1, m2, m3 = st.columns(3)
                m1.metric("Starting Value", f"${total_val:,.0f}")
                m2.metric("Estimated Drawdown", f"${t_loss:,.0f}", f"{(t_loss/total_val)*100:.2f}%")
                m3.metric("Post-Shock Value", f"${post_shock_val:,.0f}")

                fig_stress = go.Figure(go.Bar(
                    x=df_stress["Ticker"], y=df_stress["Drawdown (%)"],
                    marker_color=['#da3633' if x < 0 else '#2ea043' for x in df_stress["Drawdown (%)"]],
                    text=df_stress["Drawdown (%)"].apply(lambda x: f"{x:+.1f}%"),
                    textposition='auto'
                ))
                fig_stress.update_layout(
                    title="Asset-Level Drawdown (%)",
                    plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', margin=dict(l=0, r=0, t=30, b=0),
                    yaxis_title="Drawdown (%)", font=dict(color="#C9D1D9")
                )
                st.plotly_chart(fig_stress, use_container_width=True)

                if credit_metrics:
                    st.markdown("---")
                    st.markdown("##### 🏦 Synthetic Wholesale Credit Portfolio (Loans & Bonds)")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("Total Exposure (EAD)", f"${credit_metrics['total_ead']:,.0f}", help="Exposure at Default: Total outstanding dollar amount at risk.")
                    c2.metric("Baseline Expected Credit Loss", f"${credit_metrics['baseline_ecl']:,.0f}", help="ECL = Probability of Default (PD) × Loss Given Default (LGD) × Exposure (EAD).")
                    c3.metric("Stressed ECL", f"${credit_metrics['stressed_ecl']:,.0f}", f"+${credit_metrics['incremental_ecl']:,.0f}", help="Expected Credit Loss after applying the scenario's shock multipliers.")
                    st.caption(f"Portfolio of {credit_metrics['num_exposures']} credit exposures. The stress scenario applied a Probability of Default (PD) multiplier of {credit_metrics['pd_multiplier']}x and a Loss Given Default (LGD) multiplier of {credit_metrics['lgd_multiplier']}x.")

                st.info("💡 **How to read this:** The chart shows the estimated percentage loss (or gain) for each asset individually. The Total Drawdown is the dollar-weighted sum of these losses across the entire portfolio. \n\n*Limitations: This model uses a first-order linear approximation (Beta, Rate Modified Duration, Spread Modified Duration), assuming constant correlations and ignoring convexity. Actual large shocks may behave non-linearly.*")
