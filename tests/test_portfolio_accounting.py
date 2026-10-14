import pytest
import math
import pandas as pd
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.dependencies import AppState, get_state
from src.storage.db import SignalDatabase
from src.rebalancer.index_rebalancer import IndexRebalancer
from src.engine.risk_engine import RiskEngine

@pytest.fixture
def isolated_db(tmp_path):
    db_file = tmp_path / "test_accounting.db"
    return SignalDatabase(str(db_file))

def test_no_trade_case_zero_turnover_and_cost(isolated_db):
    """When no rebalance orders have been executed, turnover and trading costs must be exactly 0.0."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices") as mock_prices, \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        mock_prices.return_value = {t: 100.0 for t in ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]}
        state = AppState(db=isolated_db)
        state.latest_orders = pd.DataFrame()

        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)
        
        resp = client.get("/api/portfolio/metrics")
        app.dependency_overrides.clear()
        
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_turnover"] == 0.0
        assert data["est_txn_cost"] == 0.0
        assert data["initial_capital"] == 1000000.0

def test_rebalance_with_known_orders_turnover_and_cost(isolated_db):
    """Turnover must strictly equal sum of absolute executed notionals, and costs = turnover * 0.0010."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices") as mock_prices, \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        mock_prices.return_value = {t: 100.0 for t in ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]}
        state = AppState(db=isolated_db)
        
        # Simulate known executed orders: 200 shares AAPL ($20,000) and 300 shares MSFT ($30,000)
        state.latest_orders = pd.DataFrame([
            {"Ticker": "AAPL", "Action": "BUY", "Order Qty": 200.0, "Trade Value ($)": 20000.0},
            {"Ticker": "MSFT", "Action": "SELL", "Order Qty": 300.0, "Trade Value ($)": 30000.0},
        ])

        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)
        
        resp = client.get("/api/portfolio/metrics")
        app.dependency_overrides.clear()
        
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_turnover"] == 50000.0
        assert math.isclose(data["est_txn_cost"], 50.0)  # 50,000 * 0.0010 = 50.0

def test_missing_prices_returns_null_total_value(isolated_db):
    """If any asset price is missing, total_value must be null without fabricating prices."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices") as mock_prices, \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        # One price is missing (None)
        prices = {t: 100.0 for t in ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]}
        prices["AAPL"] = None
        mock_prices.return_value = prices

        state = AppState(db=isolated_db)
        
        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)
        
        resp = client.get("/api/portfolio/metrics")
        app.dependency_overrides.clear()
        
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_value"] is None

def test_drifted_portfolio_value_not_forced_to_capital(isolated_db):
    """Holdings must be persisted. When asset prices drift up 50%, portfolio value must drift up, not reset."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices") as mock_prices, \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        # Day 1: starting prices at 100.0
        tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
        mock_prices.return_value = {t: 100.0 for t in tickers}

        state1 = AppState(db=isolated_db)
        state1.sync_holdings()

        # Initial value should equal 1,000,000
        initial_shares = state1.rebalancer.current_shares
        assert all(shares is not None for shares in initial_shares.values())
        
        # Day 2: Market rally - prices drift up 50% to 150.0
        mock_prices.return_value = {t: 150.0 for t in tickers}

        # Simulate reload/restart
        state2 = AppState(db=isolated_db)
        state2.sync_holdings()

        # Shares must be identical to persisted shares
        for t in tickers:
            assert state2.rebalancer.current_shares[t] == pytest.approx(initial_shares[t])

        app.dependency_overrides[get_state] = lambda: state2
        client = TestClient(app)
        
        resp = client.get("/api/portfolio/metrics")
        app.dependency_overrides.clear()
        
        assert resp.status_code == 200
        data = resp.json()
        # With 50% price increase on default 10 shares ($10,000 -> $15,000) and $990,000 cash, value is $1,005,000
        assert data["total_value"] == pytest.approx(1005000.0, rel=1e-3)
        assert data["holdings_market_value"] == pytest.approx(15000.0, rel=1e-3)
        assert data["cash_balance"] == pytest.approx(990000.0, rel=1e-3)
        assert data["initial_capital"] == 1000000.0

def test_unclassified_event_severity_is_null_not_string(isolated_db):
    """Unclassified events must return severity as null, never 'N/A' and never 0.0."""
    unclassified_signal = {
        "entity": "AAPL",
        "event_classification": "Unclassified / Needs Review",
        "sentiment_score": 0.0,
        "impact_score": 2.0,
        "confidence": 0.5,
        "evidence_span": "Routine noise",
        "model_version": "v1.0",
        "source": "News",
        "article_hash": "unclass123",
        "published_at": "2026-10-10T12:00:00Z"
    }
    
    classified_signal = {
        "entity": "MSFT",
        "event_classification": "Credit Event",
        "sentiment_score": -0.8,
        "impact_score": 9.0,
        "confidence": 0.9,
        "evidence_span": "Default risk",
        "model_version": "v1.0",
        "source": "News",
        "article_hash": "class456",
        "published_at": "2026-10-10T12:00:00Z"
    }

    state = AppState(db=isolated_db)
    state.signals_log = [unclassified_signal, classified_signal]

    app.dependency_overrides[get_state] = lambda: state
    client = TestClient(app)

    resp = client.get("/api/risk-signals")
    app.dependency_overrides.clear()

    assert resp.status_code == 200
    signals = resp.json()
    assert len(signals) == 2
    
    unclass = next(s for s in signals if s["article_hash"] == "unclass123")
    assert unclass["severity"] is None
    assert unclass["event_classification"] == "Unclassified / Needs Review"

    credit = next(s for s in signals if s["article_hash"] == "class456")
    assert credit["severity"] == 9.0

def test_scan_counts_breakdown_duplicates_and_processed(isolated_db):
    """Scan response must split duplicates from already processed entities."""
    state = AppState(db=isolated_db)

    # Pre-populate isolated DB with a document and signal
    doc = {
        "document_hash": "doc_existing",
        "canonical_group_id": "doc_existing",
        "headline": "Existing Headline",
        "normalized_headline": "existing headline",
        "source": "News",
        "published_at": "2026-10-10T12:00:00Z",
        "is_duplicate": False,
        "duplicate_reason": None,
        "resolved_entities": ["AAPL"]
    }
    isolated_db.log_document(doc)
    a_hash = isolated_db.generate_hash("Existing Headline", "AAPL")
    isolated_db.log_signal(
        a_hash,
        {
            "entity": "AAPL",
            "event_classification": "Product Launch",
            "sentiment_score": 0.5,
            "impact_score": 4.0,
            "confidence": 0.8,
            "evidence_span": "new product",
            "model_version": "v1.0"
        },
        "Existing Headline",
        "News",
        "2026-10-10T12:00:00Z",
        "doc_existing"
    )

    app.dependency_overrides[get_state] = lambda: state
    client = TestClient(app)

    with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news") as mock_news, \
         patch("src.rebalancer.price_provider.PriceProvider.get_prices") as mock_prices:
        mock_prices.return_value = {t: 100.0 for t in ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]}
        # Return 2 news items: 1 true duplicate headline, 1 already processed entity
        mock_news.return_value = [
            {"headline": "Existing Headline", "source": "News", "published_at": "2026-10-10T12:05:00Z"},
        ]
        resp = client.post("/api/market-scan")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["stats_skipped"] == 1
        assert "stats_duplicates" in data
        assert "stats_already_processed" in data

def test_reset_runtime_endpoint(isolated_db):
    """POST /api/reset must cleanly clear runtime orders and signals and reset to baseline."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices") as mock_prices, \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        mock_prices.return_value = {t: 100.0 for t in ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]}
        state = AppState(db=isolated_db)
        state.latest_orders = pd.DataFrame([{"Ticker": "AAPL", "Action": "BUY", "Order Qty": 100.0, "Trade Value ($)": 10000.0}])
        state.signals_log = [{"entity": "AAPL", "event_classification": "Product Launch"}]

        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        resp = client.post("/api/reset")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

        # State should be reset
        assert state.latest_orders.empty
        assert len(state.signals_log) == 0

        # Metrics should report 0 turnover and baseline weights
        metrics_resp = client.get("/api/portfolio/metrics")
        app.dependency_overrides.clear()

        assert metrics_resp.status_code == 200
        metrics = metrics_resp.json()
        assert metrics["total_turnover"] == 0.0
        assert metrics["est_txn_cost"] == 0.0

