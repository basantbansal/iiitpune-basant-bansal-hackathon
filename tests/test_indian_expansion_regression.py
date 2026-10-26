"""
Regression Test Suite for Indian-Market Expansion, Multi-Currency Accounting,
Entity Disambiguation, and Execution State Integrity.
"""

import pytest
import math
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import pandas as pd

from src.api.main import app
from src.api.dependencies import AppState, get_state
from src.storage.db import SignalDatabase
from src.engine.catalog import get_catalog
from src.engine.processor import EntityResolver
from src.rebalancer.fx_provider import FXRate
from src.rebalancer.index_rebalancer import IndexRebalancer

@pytest.fixture
def isolated_db(tmp_path):
    db_file = tmp_path / "test_indian_regression.db"
    return SignalDatabase(str(db_file))

@pytest.fixture
def test_client(isolated_db):
    state = AppState(db=isolated_db)
    cat = get_catalog()
    default_prices = {
        inst.display_ticker: 2000.0 if inst.currency == "INR" else 100.0
        for inst in cat.get_all()
    }
    state.rebalancer.price_provider._prices = dict(default_prices)
    app.dependency_overrides[get_state] = lambda: state
    client = TestClient(app)
    yield client, state
    app.dependency_overrides.clear()

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


# ============================================================================
# 1. Entity Disambiguation: Strict Company Matching (All 10 Negative Cases)
# ============================================================================

def test_regression_entity_disambiguation_strictness():
    """Validates that common words like 'reliance', 'itc', 'tcs', and 'l&t' are disambiguated."""
    misleading_headlines = [
        # Reliance
        "Growing reliance on foreign oil poses serious national security risk",
        "Over-reliance on legacy software systems threatens hospital operations",
        # TCS (True Cost of Solar, Traffic Control, Tax Collection)
        "New study reveals the TCS (True Cost of Solar) across rural agriculture",
        "Government announces update to Tax Collected at Source (TCS) rules for remitters",
        "Highway department deploys AI-based Traffic Control System (TCS) to ease congestion",
        # ITC (International Trade Commission, Input Tax Credit, Investment Tax Credit)
        "ITC opens patent investigation into imported medical ultrasound transducers",
        "GST Council tightens input tax credit (ITC) rules for small enterprises",
        "Clean energy developers seek extension of federal investment tax credit (ITC)",
        # L&T (Long-term, Light & Translucent)
        "Scientists review L&T (Long-Term) outcomes of cellular therapy in leukemia patients",
        "Aerospace engineers test new L&T (Light and Translucent) composites for wings",
    ]

    legit_headlines = [
        ("Reliance Industries secures massive multi-billion green hydrogen supply contract", "RELIANCE"),
        ("Tata Consultancy Services (TCS) wins $750M cloud modernization deal with European bank", "TCS"),
        ("ITC Ltd reports 18% jump in quarterly FMCG cigarette and agribusiness profits", "ITC"),
        ("Larsen & Toubro (L&T) bags mega onshore gas pipeline project in Middle East", "LT"),
    ]

    for hl in misleading_headlines:
        resolved = EntityResolver.resolve_entities(hl)
        tickers = [r.ticker for r in resolved]
        assert "RELIANCE" not in tickers, f"False positive for RELIANCE: {hl}"
        assert "TCS" not in tickers, f"False positive for TCS: {hl}"
        assert "ITC" not in tickers, f"False positive for ITC: {hl}"
        assert "LT" not in tickers, f"False positive for LT: {hl}"

    for hl, expected_ticker in legit_headlines:
        resolved = EntityResolver.resolve_entities(hl)
        tickers = [r.ticker for r in resolved]
        assert expected_ticker in tickers, f"Failed to resolve {expected_ticker} for: {hl}"


# ============================================================================
# 2. INR-First Reporting Currency Toggle & API Persistence
# ============================================================================

def test_regression_reporting_currency_api_persistence(test_client, isolated_db):
    """Checks GET and POST /api/reporting-currency endpoints and persistence."""
    client, state = test_client

    # 1. Fetch current reporting currency
    resp = client.get("/api/reporting-currency")
    assert resp.status_code == 200
    data = resp.json()
    assert "reporting_currency" in data
    assert data["currency_symbol"] in ("₹", "$")

    # 2. Update to INR explicitly
    put_inr = client.post("/api/reporting-currency", json={"currency": "INR"})
    assert put_inr.status_code == 200
    assert put_inr.json()["reporting_currency"] == "INR"
    assert put_inr.json()["currency_symbol"] == "₹"

    # Verify state reflects INR
    assert state.reporting_currency == "INR"

    # 3. Request metrics with default currency (INR)
    metrics_inr = client.get("/api/portfolio/metrics").json()
    assert metrics_inr["reporting_currency"] == "INR"
    assert metrics_inr["reporting_currency_symbol"] == "₹"

    # 4. Request metrics with explicit query parameter override (USD)
    metrics_usd = client.get("/api/portfolio/metrics?currency=USD").json()
    assert metrics_usd["reporting_currency"] == "USD"
    assert metrics_usd["reporting_currency_symbol"] == "$"

    # 5. Verify persistence across fresh state instance
    fresh_state = AppState(db=isolated_db)
    assert fresh_state.reporting_currency == "INR"


# ============================================================================
# 3. Capital Invariance & Conservation during Universe Switching
# ============================================================================

def test_regression_universe_switching_capital_invariance(test_client):
    """
    Switching between US-only, India-only, and Mixed universes must not create or destroy capital.
    Delta NAV must equal 0 across switches when holding baseline positions.
    """
    client, state = test_client
    catalog = get_catalog()

    def mock_price_lookup(*args, **kwargs):
        tickers = args[0] if args else kwargs.get("tickers")
        if not tickers:
            tickers = [inst.display_ticker for inst in catalog.get_all()]
        prices = {}
        for t in tickers:
            inst = catalog.get_by_ticker(t)
            if inst and inst.currency == "INR":
                prices[t] = 1000.0
            else:
                prices[t] = 100.0
        return prices

    with patch.object(state.rebalancer, "fetch_current_prices", side_effect=mock_price_lookup), \
         patch("src.rebalancer.price_provider.PriceProvider.get_prices", side_effect=mock_price_lookup), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):

        # US-Only Initial
        m1 = client.get("/api/portfolio/metrics?currency=USD").json()
        assert m1["cash_usd"] == pytest.approx(990000.0, abs=1.0)
        assert m1["total_value"] == pytest.approx(1000000.0, abs=1.0)

        # Switch to Mixed-10
        client.put("/api/universe/selection", json={"selection": MIXED_10_IDS})
        m2 = client.get("/api/portfolio/metrics?currency=USD").json()
        # 5 US stocks seeded (5 * 10 * 100 = $5,000), USD cash is $995,000.
        assert m2["cash_usd"] == pytest.approx(995000.0, abs=1.0)
        # Without INR capital allocation or live FX, cross-currency NAV is truthful null
        assert m2["cash_inr"] == 0.0

        # Switch back to US-Only
        client.put("/api/universe/selection", json={"selection": US_10_IDS})
        m3 = client.get("/api/portfolio/metrics?currency=USD").json()
        assert m3["cash_usd"] == pytest.approx(990000.0, abs=1.0)
        assert m3["total_value"] == pytest.approx(1000000.0, abs=1.0)


# ============================================================================
# 4. Withheld Order Holdings Non-Mutation
# ============================================================================

def test_regression_withheld_orders_do_not_mutate_holdings(test_client):
    """
    Orders with missing or fallback quotes must be withheld.
    Current shares, cash balances, and executed trade quantities must not mutate.
    """
    client, state = test_client
    catalog = get_catalog()

    # Switch to India-only where fallback prices exist
    client.put("/api/universe/selection", json={"selection": IN_10_IDS})
    in_tickers = [catalog.get_by_id(i_id).display_ticker for i_id in IN_10_IDS]

    # Pre-shares: 10 each
    for t in in_tickers:
        assert state.rebalancer.current_shares[t] == 10.0

    # Simulate rebalance with positive signal for RELIANCE
    signals = [{
        "entity": "RELIANCE",
        "sentiment_score": 0.8,
        "impact_score": 8,
        "event_classification": "Contract Win"
    }]

    # PriceProvider has fallback prices (is_fallback=True)
    state.rebalancer.price_provider._prices = {}
    state.rebalancer.price_provider._reference_prices = {t: 2500.0 for t in in_tickers}

    df_orders = state.rebalancer.rebalance(signals)
    rel_order = df_orders[df_orders["Ticker"] == "RELIANCE"].iloc[0]

    # Withheld rule: Action remains HOLD or execution status WITHHELD_FALLBACK_PRICE
    assert rel_order["Action"] == "HOLD"
    assert rel_order["Order Qty"] == 0.0
    assert bool(rel_order["Is Executable"]) is False
    assert rel_order["Execution Status"] == "WITHHELD_FALLBACK_PRICE"

    # Current shares are strictly preserved
    assert state.rebalancer.current_shares["RELIANCE"] == 10.0


# ============================================================================
# 5. Explainability Non-Contradiction
# ============================================================================

def test_regression_explainability_non_contradiction(test_client):
    """
    Ensures that when an order is withheld due to missing or fallback quotes,
    the explainability text does not claim a BUY/SELL order was executed for 0.00 shares.
    """
    client, state = test_client
    catalog = get_catalog()

    client.put("/api/universe/selection", json={"selection": IN_10_IDS})
    in_tickers = [catalog.get_by_id(i_id).display_ticker for i_id in IN_10_IDS]

    # Target weight moves to 11.10% on positive sentiment
    signals = [{
        "entity": "RELIANCE",
        "sentiment_score": 0.8,
        "impact_score": 8,
        "event_classification": "Contract Win"
    }]
    state.rebalancer.price_provider._prices = {}
    state.rebalancer.price_provider._reference_prices = {t: 2500.0 for t in in_tickers}

    df = state.rebalancer.rebalance(signals)
    state.latest_orders = df

    # Fetch stock details for RELIANCE
    resp = client.get("/api/stocks/RELIANCE/details")
    assert resp.status_code == 200
    details = resp.json()

    # Rationale must not contradict execution state
    rationale = details["rationale_text"]
    assert "BUY order for 0.00 shares" not in rationale
    assert "SELL order for 0.00 shares" not in rationale
    if details["is_executable"] is False:
        assert details["execution_status"].startswith("WITHHELD_")
        assert details["action"] == "HOLD"
