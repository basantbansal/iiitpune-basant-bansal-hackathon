import os
import pytest
from fastapi.testclient import TestClient
from src.api.main import app
import src.api.dependencies as deps
import sqlite3

@pytest.fixture
def isolated_db_and_news(mocker):
    # Mock MarketNewsIngestion to return a deterministic list of articles
    mock_articles = [
        {"headline": "Apple launches new iPhone 16", "source": "TechNews", "published_at": "2024-01-01T12:00:00Z"},
        {"headline": "Microsoft acquires AI startup", "source": "BusinessWire", "published_at": "2024-01-01T12:05:00Z"}
    ]
    mocker.patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=mock_articles)
    
    # Mock RiskEngine to return deterministic signals so we don't hit LLM APIs
    from src.engine.risk_engine import RiskSignal
    def mock_analyze(self, text, entity, source):
        return RiskSignal(entity=entity, event_classification="Product Launch", sentiment_score=0.9, impact_score=8.0, confidence=0.95, headline=text, evidence_span="Mock")
    mocker.patch("src.engine.risk_engine.RiskEngine.analyze", mock_analyze)
    
    # Mock EntityResolver to return deterministic entities
    from src.engine.processor import ResolvedEntity
    def mock_resolve(text):
        if "Apple" in text:
            return [ResolvedEntity(ticker="AAPL", match_type="Mock", confidence=0.99, matched_text="Apple")]
        elif "Microsoft" in text:
            return [ResolvedEntity(ticker="MSFT", match_type="Mock", confidence=0.99, matched_text="Microsoft")]
        return []
    mocker.patch("src.engine.processor.EntityResolver.resolve_entities", mock_resolve)
    
    # Patch DB to use a temporary file instead of the real DB
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        temp_db_path = f.name
        
    def mock_db():
        from src.storage.db import SignalDatabase
        return SignalDatabase(temp_db_path)
        
    mocker.patch("src.api.dependencies.SignalDatabase", mock_db)
    
    # Clear the global state
    deps.state = None
    yield
    deps.state = None
    if os.path.exists(temp_db_path):
        os.remove(temp_db_path)

def test_duplicate_news_regression(isolated_db_and_news):
    client = TestClient(app)
    
    # First live scan
    scan_resp = client.post("/api/market-scan")
    assert scan_resp.status_code == 200
    
    state_resp = client.get("/api/risk-signals")
    assert state_resp.status_code == 200
    first_run_signals = len(state_resp.json())
    assert first_run_signals > 0, "Should have processed the mock articles"
    
    # 2. Simulate fresh session with populated history by clearing global state
    deps.state = None
    client2 = TestClient(app)
    
    # Initial state should be restored from DB
    state_resp2 = client2.get("/api/risk-signals")
    assert state_resp2.status_code == 200
    assert len(state_resp2.json()) == first_run_signals, f"Fresh session failed to load processed articles. Expected {first_run_signals}, got {len(state_resp2.json())}"
    
    # Click scan. It should not insert duplicates, but might skip them.
    scan_resp2 = client2.post("/api/market-scan")
    assert scan_resp2.status_code == 200
    
    state_resp3 = client2.get("/api/risk-signals")
    df2_after = len(state_resp3.json())
    assert df2_after == first_run_signals, f"Scan duplicated signals. Expected {first_run_signals}, got {df2_after}"


