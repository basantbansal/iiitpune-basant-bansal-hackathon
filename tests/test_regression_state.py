import pytest
from fastapi.testclient import TestClient
import sqlite3
import os
import json
from unittest.mock import patch, MagicMock
from src.api.main import app
from src.api.dependencies import get_state, AppState

@pytest.fixture
def temp_db(tmp_path):
    db_path = tmp_path / "test_risk_data.db"
    
    # Initialize DB
    from src.storage.db import SignalDatabase
    db = SignalDatabase(str(db_path))
    
    # Pre-populate with one signal and one document
    db.log_document({
        "document_hash": "doc123",
        "canonical_group_id": "doc123",
        "headline": "Test Headline",
        "normalized_headline": "test headline",
        "source": "News",
        "published_at": "2026-10-10T12:00:00Z",
        "is_duplicate": False,
        "duplicate_reason": None,
        "resolved_entities": ["AAPL"]
    })
    
    db.log_signal(
        "art123", 
        {
            "entity": "AAPL",
            "event_classification": "Macroeconomic",
            "sentiment_score": -0.8,
            "impact_score": 8.0,
            "confidence": 0.9,
            "evidence_span": "Bad news for AAPL",
            "model_version": "v1.0"
        },
        "Test Headline",
        "News",
        "2026-10-10T12:00:00Z",
        "doc123"
    )
    
    return str(db_path)

@pytest.fixture
def test_app(temp_db):
    with patch("src.api.dependencies.SignalDatabase", lambda: __import__('src.storage.db', fromlist=['SignalDatabase']).SignalDatabase(temp_db)):
        with patch("src.rebalancer.price_provider.PriceProvider.get_prices") as mock_prices:
            # Set a dummy return value for all tickers
            mock_prices.return_value = {t: 100.0 for t in ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NVDA", "TSLA", "JPM", "JNJ", "XOM"]}
            state = AppState()
            app.dependency_overrides[get_state] = lambda: state
            yield state
            app.dependency_overrides.clear()

@pytest.fixture
def client(test_app):
    return TestClient(app)

def test_fresh_session_loads_existing_state(client, test_app):
    # Test 1: Fresh session with existing SQLite database
    assert len(test_app.signals_log) == 1
    assert test_app.last_updated == "2026-10-10T12:00:00Z"
    assert test_app.latest_orders.empty
    
    # Test 3: Existing signals appearing after refresh
    resp = client.get("/api/risk-signals")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["entity"] == "AAPL"
    
    # Check portfolio weights stay at baseline without automatic rebalance on startup
    resp = client.get("/api/portfolio")
    data = resp.json()
    for item in data:
        assert item["target_weight"] == pytest.approx(item["baseline_weight"], abs=1e-5)

@patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news")
def test_scan_all_duplicates(mock_fetch, client, test_app):
    # Test 2: A scan where every article is a duplicate
    mock_fetch.return_value = [{
        "headline": "Test Headline", # Will resolve to same hash
        "source": "News",
        "published_at": "2026-10-10T12:05:00Z"
    }]
    
    resp = client.post("/api/market-scan")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stats_processed"] == 0
    assert data["stats_skipped"] == 1
    assert data["message"] == "Scan complete. All retrieved articles skipped (duplicates)."
    
    # Ensure no new signals added to memory
    assert len(test_app.signals_log) == 1

@patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news")
@patch("src.engine.risk_engine.RiskEngine.analyze")
def test_scan_new_signals(mock_analyze, mock_fetch, client, test_app):
    # Test 4: A scan that inserts new signals
    mock_fetch.return_value = [{
        "headline": "Completely New Headline for MSFT",
        "source": "News",
        "published_at": "2026-10-10T12:10:00Z"
    }]
    
    class MockSig:
        def to_dict(self):
            return {
                "entity": "MSFT", "event_classification": "Product Launch", 
                "sentiment_score": 0.5, "impact_score": 5.0, 
                "confidence": 0.8, "evidence_span": "new product", "model_version": "v1.0"
            }
    mock_analyze.return_value = MockSig()
    
    resp = client.post("/api/market-scan")
    assert resp.status_code == 200
    data = resp.json()
    assert data["stats_processed"] == 1
    assert "New signals processed" in data["message"] or "Found 1 risk signals" in data["message"] or "Scan complete" in data["message"]
    assert len(data["new_signals"]) == 1
    
    # DB and memory should have 2
    assert len(test_app.signals_log) == 2
    assert len(test_app.db.get_all_signals()) == 2

@patch("src.rebalancer.price_provider.PriceProvider.get_prices")
def test_missing_market_prices(mock_get_prices, client, test_app):
    # Test 5: Missing market prices
    # Mock price provider to return None for everything
    mock_get_prices.return_value = {t: None for t in test_app.rebalancer.tickers}
    
    resp = client.get("/api/portfolio")
    assert resp.status_code == 200
    data = resp.json()
    assert data[0]["price"] is None
    
def test_portfolio_config_persistence(client, test_app, temp_db):
    # Test 6: Portfolio configuration loading and persistence
    # 1. Update config via POST
    resp = client.post("/api/config", json={
        "initial_capital": 2000000.0,
        "alpha_tilt": 0.08,
        "data_mode": "Offline",
        "max_items": 5
    })
    assert resp.status_code == 200
    
    # 2. Verify state updated
    assert test_app.rebalancer.initial_capital == 2000000.0
    assert test_app.rebalancer.alpha_tilt == 0.08
    assert test_app.data_mode == "Offline"
    
    # 3. Verify GET returns updated config
    resp = client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["initial_capital"] == 2000000.0
    assert data["alpha_tilt"] == 0.08
    
    # 4. Verify DB persistence across a new instance (simulating restart)
    with patch("src.api.dependencies.SignalDatabase", lambda: __import__('src.storage.db', fromlist=['SignalDatabase']).SignalDatabase(temp_db)):
        new_state = AppState()
        assert new_state.rebalancer.initial_capital == 2000000.0
        assert new_state.rebalancer.alpha_tilt == 0.08
        assert new_state.data_mode == "Offline"
        assert new_state.max_items == 5
