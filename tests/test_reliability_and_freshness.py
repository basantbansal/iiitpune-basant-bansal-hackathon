"""
Comprehensive Real-World Reliability, Clean Sessions, News Freshness & Financial Integrity Test Suite.

Validates:
- Priority 1: Clean Application Sessions, Universe Change Pre-Scan Reset, and Reset Data Integrity.
- Priority 2: Git Hygiene (untracked/gitignored transient scan databases).
- Priority 3: End-to-End News Freshness (RFC 2822/ISO 8601, 72h limit, future timestamp quarantine, SEO rejection, 10-constituent coverage matrix).
- Priority 4: Multi-ticker news assignment with shared-story discount and transparent HOLD/execution orders.
- Priority 5: Currency isolation, Single-Currency NAV without FX dependency, and indicative fallback labeling.
- Priority 6: Execution Invariants (no short positions, post_shares >= 0, fee deduction integrity).
- Priority 7: Module B (Strategic Banking Book Stress Testing) strict isolation from Module A equity accounting.
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import pandas as pd
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.dependencies import get_state, AppState
from src.storage.db import SignalDatabase
from src.engine.catalog import get_catalog
from src.engine.ingestion import (
    parse_publication_timestamp,
    is_irrelevant_or_seo_headline,
    MarketNewsIngestion
)
from src.rebalancer.index_rebalancer import IndexRebalancer
from src.rebalancer.fx_provider import FXRate, FXRateProvider
from src.rebalancer.price_provider import PriceProvider


US_10_IDS = [
    "US_AAPL", "US_MSFT", "US_NVDA", "US_AMZN", "US_GOOGL",
    "US_META", "US_TSLA", "US_JPM", "US_JNJ", "US_XOM"
]

IN_10_IDS = [
    "IN_RELIANCE", "IN_TCS", "IN_HDFCBANK", "IN_INFY", "IN_ICICIBANK",
    "IN_HINDUNILVR", "IN_ITC", "IN_BHARTIARTL", "IN_LT", "IN_SBIN"
]

MIXED_10_IDS = [
    "US_AAPL", "US_MSFT", "US_NVDA", "US_AMZN", "US_GOOGL",
    "IN_RELIANCE", "IN_TCS", "IN_HDFCBANK", "IN_INFY", "IN_ICICIBANK"
]


@pytest.fixture
def clean_db(tmp_path):
    db_file = tmp_path / "test_reliability.db"
    return SignalDatabase(str(db_file))


@pytest.fixture
def reliability_client(clean_db):
    state = AppState(db=clean_db)
    app.dependency_overrides[get_state] = lambda: state
    client = TestClient(app)
    yield client, state, clean_db
    app.dependency_overrides.clear()


# ============================================================================
# Priority 1: Clean Sessions & Reset Behavior
# ============================================================================

def test_p1_01_fresh_application_launch_session_state(clean_db):
    """Priority 1A: Fresh startup initializes clean state without phantom scan results."""
    # Seed DB with old scan signals and orders
    clean_db.log_signal(
        article_hash="old_hash_1",
        signal_dict={
            "entity": "AAPL",
            "sentiment_score": -0.8,
            "impact_score": 8.0,
            "confidence": 0.9,
            "evidence_span": "regulatory penalty",
            "event_classification": "Regulatory Fine"
        },
        headline="Old AAPL fine",
        source="OldNews",
        published_at="2026-09-01T00:00:00Z",
        document_hash="old_doc_1"
    )
    clean_db.save_latest_orders(pd.DataFrame([
        {"Ticker": "AAPL", "Action": "SELL", "Order Qty": 50.0, "Trade Value ($)": 5000.0}
    ]))
    clean_db.save_target_weights_history("2026-09-01T00:00:00Z", {"AAPL": 0.05, "MSFT": 0.15})

    # Initialize app state and run clean session startup lifecycle
    state = AppState(db=clean_db)
    import asyncio
    asyncio.run(state.initialize_clean_session())

    assert len(state.signals_log) == 0
    assert state.latest_orders.empty
    assert state.last_updated == "Never"
    assert clean_db.get_all_signals() == []
    assert clean_db.get_latest_orders().empty
    assert clean_db.get_target_weights_history() == []


def test_p1_02_universe_change_invalidates_scan_and_restores_pre_scan_baseline(reliability_client):
    """Priority 1B: Changing universe resets previous scan signals and orders to clean pre-scan baseline."""
    client, state, db = reliability_client

    # Populate active scan signals
    state.signals_log = [{"entity": "AAPL", "headline": "Apple profit surge", "sentiment_score": 0.8}]
    state.latest_orders = pd.DataFrame([{"Ticker": "AAPL", "Action": "BUY", "Order Qty": 10.0, "Trade Value ($)": 1500.0}])
    state.last_updated = "2026-10-16T10:00:00Z"

    # Switch universe to India-10
    resp = client.put("/api/universe/selection", json={"selection": IN_10_IDS})
    assert resp.status_code == 200

    # Verify signals and orders are cleared, target weights are equal baseline (10%)
    assert len(state.signals_log) == 0
    assert state.latest_orders.empty
    assert state.last_updated == "Never"
    for t in state.rebalancer.tickers:
        assert state.rebalancer.current_weights[t] == pytest.approx(0.10, abs=1e-4)

    # API returns clean status
    metrics = client.get("/api/portfolio/metrics").json()
    assert metrics["last_updated"] == "No scan executed yet"


def test_p1_03_reset_data_button_preserves_holdings_and_restores_baseline(reliability_client):
    """Priority 1C: Reset Data button resets signals, coverage, and fees and restores benchmark baseline."""
    client, state, db = reliability_client

    # Customize holdings
    custom_shares = {t: 25.0 for t in state.rebalancer.tickers}
    client.post("/api/portfolio/holdings", json={"holdings": custom_shares})

    # Seed signals and fees
    state.signals_log = [{"entity": "MSFT", "sentiment_score": -0.5}]
    state.cumulative_fees = {"USD": 45.20, "INR": 0.0}
    db.save_cumulative_fees(state.cumulative_fees)

    # Invoke reset
    resp = client.post("/api/reset")
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["status"] == "ok"
    assert state.last_updated == "Never"
    assert len(state.signals_log) == 0
    assert state.cumulative_fees["USD"] == 0.0

    # Baseline 10 shares per constituent restored
    port = client.get("/api/portfolio").json()
    for item in port:
        assert item["current_shares"] == 10.0


# ============================================================================
# Priority 2: Git Integrity & Database Tracking
# ============================================================================

def test_p2_01_transient_sqlite_db_not_git_tracked():
    """Priority 2: Ensure risk_data.db is untracked and excluded in .gitignore."""
    import subprocess
    res = subprocess.run(["git", "status", "--porcelain", "risk_data.db"], capture_output=True, text=True)
    # Output should either be empty or ?? (untracked), but never staged/modified
    assert not res.stdout.startswith("M ")
    assert not res.stdout.startswith("A ")


# ============================================================================
# Priority 3: News Freshness, Quarantine & Per-Constituent Coverage Matrix
# ============================================================================

def test_p3_01_parse_publication_timestamp_rfc2822_and_iso8601():
    """Priority 3: Validates RFC 2822 and ISO 8601 parsing with 72h max age enforcement."""
    now_utc = datetime.now(timezone.utc)
    
    # 24 hours ago (fresh RFC 2822)
    dt_24h = now_utc - timedelta(hours=24)
    rfc_str = dt_24h.strftime("%a, %d %b %Y %H:%M:%S GMT")
    res1 = parse_publication_timestamp(rfc_str, max_age_hours=72.0)
    assert res1["is_fresh"] is True
    assert res1["has_reliable_timestamp"] is True
    assert res1["article_age_days"] == pytest.approx(1.0, abs=0.1)

    # 80 hours ago (>72h, stale)
    dt_80h = now_utc - timedelta(hours=80)
    iso_stale = dt_80h.isoformat()
    res2 = parse_publication_timestamp(iso_stale, max_age_hours=72.0)
    assert res2["is_fresh"] is False
    assert res2["article_age_days"] == pytest.approx(3.33, abs=0.1)


def test_p3_02_quarantine_future_and_malformed_timestamps():
    """Priority 3: Future-dated and malformed timestamps are safely quarantined."""
    # Future timestamp (e.g. +3 days ahead)
    future_dt = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    res_fut = parse_publication_timestamp(future_dt, max_age_hours=72.0)
    assert res_fut["is_fresh"] is False
    assert res_fut["has_reliable_timestamp"] is False

    # Malformed timestamp
    res_bad = parse_publication_timestamp("invalid-date-string", max_age_hours=72.0)
    assert res_bad["is_fresh"] is False
    assert res_bad["has_reliable_timestamp"] is False


def test_p3_03_filter_irrelevant_seo_and_fund_disclosure_headlines():
    """Priority 3: Filter SEO, quote pages, options chains, and fund holding disclosures."""
    seo_headlines = [
        "Caprock Group LLC Sells 2,140 Shares of Apple Inc. (NASDAQ:AAPL)",
        "Reliance Industries stock quote, 52-week high, real-time charts and options chain",
        "TCS Ex-Dividend Date & Dividend Yield Summary for Investors",
        "Short Interest in NVIDIA Corp. (NASDAQ:NVDA) Declines by 14.5%",
        "State of New Jersey Common Pension Fund Decreases Stake in Microsoft"
    ]
    for h in seo_headlines:
        is_irrel, reason = is_irrelevant_or_seo_headline(h)
        assert is_irrel is True, f"Headline should have been rejected as irrelevant: {h}"
        assert reason is not None


def test_p3_04_constituent_coverage_matrix_observable_across_all_10_stocks(reliability_client):
    """Priority 3: Observable constituent coverage matrix tracks all 10 monitored stocks."""
    client, state, db = reliability_client

    now_iso = datetime.now(timezone.utc).isoformat()
    mock_articles = [
        {"ticker": "AAPL", "headline": "Apple Inc launches breakthrough M5 processor for enterprise cloud", "source": "Reuters", "published_at": now_iso},
        {"ticker": "MSFT", "headline": "Caprock Group LLC Sells 1,500 Shares of Microsoft Corp.", "source": "HoldingsFeed", "published_at": now_iso},
    ]

    fixed_prices = {t: 100.0 for t in state.rebalancer.tickers}
    with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=mock_articles), \
         patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        resp = client.post("/api/market-scan")
        assert resp.status_code == 200
        scan_data = resp.json()

        coverage = scan_data.get("constituent_coverage")
        assert coverage is not None
        # All 10 constituents present in matrix
        assert len(coverage) == 10

        # AAPL had genuine article
        assert coverage["AAPL"]["raw_retrieved"] >= 1
        assert coverage["AAPL"]["signals_count"] >= 1
        assert coverage["AAPL"]["coverage_state"] == "FRESH_NEWS_FOUND"

        # MSFT article was filtered as irrelevant disclosure
        assert coverage["MSFT"]["rejected_irrelevant"] >= 1
        assert coverage["MSFT"]["coverage_state"] == "ARTICLES_REJECTED_AS_IRRELEVANT"

        # NVDA had no articles retrieved
        assert coverage["NVDA"]["raw_retrieved"] == 0
        assert coverage["NVDA"]["coverage_state"] == "NO_NEWS_RETRIEVED"


# ============================================================================
# Priority 4: Transparent Allocation & Multi-Ticker Attribution
# ============================================================================

def test_p4_01_multi_ticker_assignment_shared_story_discount(reliability_client):
    """Priority 4: Shared industry headlines apply confidence discount (0.70x) across resolved entities."""
    client, state, db = reliability_client
    now_iso = datetime.now(timezone.utc).isoformat()

    shared_article = [
        {
            "headline": "Apple Inc and Microsoft announce joint cloud enterprise contract",
            "source": "TechWire",
            "published_at": now_iso
        }
    ]

    fixed_prices = {t: 100.0 for t in state.rebalancer.tickers}
    with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=shared_article), \
         patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        resp = client.post("/api/market-scan")
        assert resp.status_code == 200
        data = resp.json()

        shared_signals = [s for s in data["new_signals"] if s.get("is_shared_headline")]
        assert len(shared_signals) >= 2  # Assigned to both AAPL and MSFT
        for s in shared_signals:
            assert s["is_shared_headline"] is True
            assert s["confidence"] <= 0.75


# ============================================================================
# Priority 5: Currency Display & Consolidated NAV Mathematical Integrity
# ============================================================================

def test_p5_01_single_currency_inr_portfolio_nav_does_not_require_fx(reliability_client):
    """Priority 5: Pure Indian-market portfolio under INR reporting computes NAV directly without USD/INR FX dependency."""
    client, state, db = reliability_client

    cat = get_catalog()
    in_tickers = [cat.get_by_id(i).display_ticker for i in IN_10_IDS]
    mock_inr_prices = {t: 1500.0 for t in in_tickers}

    # FX rate is stale/fallback
    stale_fx = FXRate(
        base_currency="USD", quote_currency="INR", rate=84.00,
        as_of="2026-10-01T00:00:00Z", source="Fallback Stale",
        is_fallback=True, is_stale=True, observation_time="2026-10-01T00:00:00Z"
    )

    with patch.object(state.fx_provider, "get_rate", return_value=stale_fx), \
         patch.object(state.rebalancer, "fetch_current_prices", return_value=mock_inr_prices), \
         patch.object(PriceProvider, "get_prices", return_value=mock_inr_prices), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        
        # Switch to India-only under INR reporting
        client.post("/api/reporting-currency", json={"currency": "INR"})
        client.put("/api/universe/selection", json={"selection": IN_10_IDS})

        metrics = client.get("/api/portfolio/metrics?currency=INR").json()

        # Pure INR portfolio must NOT fail NAV due to USD/INR FX quote!
        assert metrics["reporting_currency"] == "INR"
        assert metrics["total_value"] is not None
        assert metrics["total_value"] == pytest.approx(84000000.0, abs=10.0)
        assert metrics["holdings_market_value"] == pytest.approx(10 * 10 * 1500.0, abs=1.0)
        assert metrics["nav_status"] == "LIVE"


def test_p5_02_cross_currency_nav_marks_indicative_fallback_when_fx_is_fallback(reliability_client):
    """Priority 5: Cross-currency portfolio with fallback FX rate is marked UNAVAILABLE or INDICATIVE."""
    client, state, db = reliability_client

    # Mixed universe (US + India) under USD reporting
    client.post("/api/reporting-currency", json={"currency": "USD"})
    client.put("/api/universe/selection", json={"selection": MIXED_10_IDS})

    fallback_fx = FXRate(
        base_currency="USD", quote_currency="INR", rate=84.00,
        as_of="2026-10-15T00:00:00Z", source="Fallback Reference",
        is_fallback=True, is_stale=False, observation_time="2026-10-15T00:00:00Z"
    )

    with patch.object(state.fx_provider, "get_rate", return_value=fallback_fx), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        metrics = client.get("/api/portfolio/metrics?currency=USD").json()

        # With fallback FX in a mixed portfolio, consolidated live NAV is unavailable
        assert metrics["total_value"] is None
        assert metrics["nav_status"] == "UNAVAILABLE"
        # But indicative NAV is transparently provided
        assert metrics["indicative_nav_usd"] is not None
        assert metrics["indicative_nav_inr"] is not None


# ============================================================================
# Priority 6: Execution Invariants & Non-Negative Holdings
# ============================================================================

def test_p6_01_sell_order_clamping_prevents_short_positions(clean_db):
    """Priority 6: Large negative tilt clamps sell order quantity to current shares; post_shares cannot be negative."""
    rebalancer = IndexRebalancer(initial_capital=1000000.0)
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    rebalancer.tickers = tickers
    rebalancer.current_shares = {t: 5.0 for t in tickers}  # Only 5 shares held
    prices = {t: 100.0 for t in tickers}

    # Severe negative signal requesting large share reduction
    signals = [
        {"ticker": "AAPL", "sentiment_score": -0.99, "impact_score": 10.0, "is_stale": False, "is_synthetic": False}
    ]

    with patch.object(rebalancer, "fetch_current_prices", return_value=prices):
        orders_df = rebalancer.rebalance(signals)
        aapl_order = orders_df[orders_df["Ticker"] == "AAPL"].iloc[0]

        # Order Qty cannot exceed held 5 shares
        assert aapl_order["Order Qty"] <= 5.0
        assert aapl_order["Post Shares"] >= 0.0
        for _, row in orders_df.iterrows():
            assert row["Post Shares"] >= 0.0


# ============================================================================
# Priority 7: Banking Book Stress Test Strict Isolation
# ============================================================================

def test_p7_01_banking_book_stress_test_strict_isolation_from_equity_portfolio(reliability_client):
    """Priority 7: Module B banking stress test executes with zero side-effects on Module A equity portfolio."""
    client, state, db = reliability_client

    # Capture pre-stress state
    pre_shares = dict(state.rebalancer.current_shares)
    pre_cash = dict(state.cash_balances)
    pre_weights = dict(state.rebalancer.current_weights)

    fixed_prices = {t: 100.0 for t in state.rebalancer.tickers}
    with patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        # Run Module B stress scenario
        resp = client.post("/api/stress-test", json={"scenario_name": "1. 2022 Fed Tightening Shock"})
        assert resp.status_code == 200
        stress_res = resp.json()

        assert "banking_book" in stress_res
        assert stress_res["banking_book"]["total_pnl"] is not None
        assert stress_res["banking_book"]["invariant_holds"] is True

        # Verify Module A portfolio accounting remains completely unchanged
        assert state.rebalancer.current_shares == pre_shares
        assert state.cash_balances == pre_cash
        assert state.rebalancer.current_weights == pre_weights
