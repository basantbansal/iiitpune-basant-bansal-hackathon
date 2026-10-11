import pytest
from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)

def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

def test_get_portfolio():
    response = client.get("/api/portfolio")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert "ticker" in data[0]

def test_get_stock_details():
    response = client.get("/api/stocks/AAPL/details")
    assert response.status_code == 200
    data = response.json()
    assert data["ticker"] == "AAPL"
    assert "price" in data

def test_get_stock_details_not_found():
    response = client.get("/api/stocks/UNKNOWN/details")
    assert response.status_code == 404

def test_scan_behavior(mocker):
    # Mocking the fetch_live_news to not hit external network
    mocker.patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=[])
    
    response = client.post("/api/market-scan")
    assert response.status_code == 200
    data = response.json()
    assert "message" in data

def test_missing_prices_safety(mocker):
    # Mock price provider to return None for one of the assets
    prices_dict = {t: 100.0 for t in ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]}
    prices_dict["AAPL"] = None
    
    mocker.patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value=prices_dict)
    
    response = client.post("/api/stress-test", json={"scenario_name": "Tech Bubble Burst"})
    assert response.status_code == 400
    assert "Stress test unavailable due to missing market prices." in response.json()["detail"]

def test_risk_signals_severity(mocker):
    # Mock db to return a fake signal
    fake_signal = {
        "entity": "AAPL",
        "headline": "Test event",
        "sentiment_score": -0.8,
        "event_classification": "Credit Event",
        "impact_score": 9,
        "confidence": 0.9,
        "evidence_span": "test evidence",
        "model_version": "test",
        "source": "News",
        "article_hash": "testhash",
        "published_at": "2026-10-10"
    }
    mocker.patch("src.storage.db.SignalDatabase.get_all_signals", return_value=[fake_signal])
    
    # We must reset runtime to load our mocked db return
    import asyncio
    from src.api.dependencies import get_state
    state = get_state()
    state.signals_log = [fake_signal]
    
    response = client.get("/api/risk-signals")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["severity"] == 9.0  # From RiskEngine base_severities for Credit Event
    assert data[0]["event_classification"] == "Credit Event"
    assert data[0]["evidence"] == "test evidence"
