"""
Integration test validating the full demo lifecycle and API contract.
Replaces the legacy Streamlit prototype test with active validation of:
- Clean launch state
- Offline crisis replay scan and rebalancing
- Target weight and order derivation
- Universe switching and state invalidation
- Reset semantics and benchmark restoration
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch
from src.api.main import app
from src.api.dependencies import get_state, AppState
from src.storage.db import SignalDatabase


@pytest.fixture
def clean_demo_state(tmp_path):
    db_file = str(tmp_path / "demo_flow_lifecycle.db")
    custom_db = SignalDatabase(db_file)

    with patch("src.api.dependencies.SignalDatabase", return_value=custom_db):
        state = AppState()
        state.db = custom_db
        state.data_mode = "Offline Crisis Replay"
        app.dependency_overrides[get_state] = lambda: state
        yield state, custom_db
        app.dependency_overrides.clear()


def test_demo_flow_comprehensive_api_lifecycle(clean_demo_state):
    state, db = clean_demo_state
    client = TestClient(app)

    # ---------------------------------------------------------
    # Stage 1: Fresh Launch Verification
    # ---------------------------------------------------------
    p_resp = client.get("/api/portfolio")
    assert p_resp.status_code == 200
    portfolio_rows = p_resp.json()
    assert isinstance(portfolio_rows, list)
    assert len(portfolio_rows) == 10

    m_resp = client.get("/api/portfolio/metrics")
    assert m_resp.status_code == 200
    m_data = m_resp.json()
    assert m_data["last_updated"] == "No scan executed yet"

    # Verify no old signals or simulated orders before scan
    sig_resp = client.get("/api/risk-signals")
    assert sig_resp.status_code == 200
    assert len(sig_resp.json()) == 0

    ord_resp = client.get("/api/orders")
    assert ord_resp.status_code == 200
    assert len(ord_resp.json()) == 0

    cov_resp = client.get("/api/market-scan/coverage")
    assert cov_resp.status_code == 200
    cov_data = cov_resp.json()
    assert cov_data["total_constituents"] == 10
    for item in cov_data["coverage"]:
        assert item["coverage_state"] in ["PENDING", "NO_SCAN_EXECUTED_YET"]
        assert item["signals_count"] == 0

    # ---------------------------------------------------------
    # Stage 2: Execute Replay Market Scan & Rebalancing
    # ---------------------------------------------------------
    scan_resp = client.post("/api/market-scan")
    assert scan_resp.status_code == 200
    scan_data = scan_resp.json()
    assert "message" in scan_data
    assert len(scan_data["new_signals"]) > 0

    # Signals and orders are now populated
    sig_resp2 = client.get("/api/risk-signals")
    assert sig_resp2.status_code == 200
    assert len(sig_resp2.json()) > 0

    ord_resp2 = client.get("/api/orders")
    assert ord_resp2.status_code == 200
    orders = ord_resp2.json()
    assert len(orders) > 0

    # Verify orders contain execution rationale and valid quantities
    for order in orders:
        assert "Ticker" in order
        assert "Action" in order
        assert order["Action"] in ["BUY", "SELL", "HOLD"]
        assert "Target Shares" in order
        assert float(order["Target Shares"]) >= 0.0

    # Portfolio metrics timestamp is updated
    m_data2 = client.get("/api/portfolio/metrics").json()
    assert m_data2["last_updated"] not in ["Never", "No scan executed yet"]

    # Coverage matrix reflects scanned items
    cov_resp2 = client.get("/api/market-scan/coverage")
    assert cov_resp2.status_code == 200
    cov_data2 = cov_resp2.json()
    assert cov_data2["total_signals"] > 0

    # ---------------------------------------------------------
    # Stage 3: Universe Switching Invalidation
    # ---------------------------------------------------------
    indian_ids = [
        "IN_RELIANCE", "IN_TCS", "IN_HDFCBANK", "IN_INFY", "IN_ICICIBANK",
        "IN_HINDUNILVR", "IN_ITC", "IN_BHARTIARTL", "IN_LT", "IN_SBIN"
    ]
    switch_resp = client.put("/api/universe/selection", json={"selection": indian_ids})
    assert switch_resp.status_code == 200
    switch_data = switch_resp.json()
    assert switch_data["status"] == "ok"
    assert len(switch_data["selection"]) == 10

    # Set reporting currency to INR for the Indian universe
    client.post("/api/reporting-currency", json={"currency": "INR"})
    m_data3 = client.get("/api/portfolio/metrics").json()
    assert m_data3["last_updated"] == "No scan executed yet"
    assert m_data3["reporting_currency"] == "INR"

    p_rows3 = client.get("/api/portfolio").json()
    tickers = [p["ticker"] for p in p_rows3]
    assert "RELIANCE" in tickers
    assert "AAPL" not in tickers

    sig_resp3 = client.get("/api/risk-signals")
    assert sig_resp3.status_code == 200
    assert len(sig_resp3.json()) == 0

    ord_resp3 = client.get("/api/orders")
    assert ord_resp3.status_code == 200
    assert len(ord_resp3.json()) == 0

    # ---------------------------------------------------------
    # Stage 4: Reset Semantics
    # ---------------------------------------------------------
    reset_resp = client.post("/api/reset")
    assert reset_resp.status_code == 200

    m_data4 = client.get("/api/portfolio/metrics").json()
    assert m_data4["last_updated"] == "No scan executed yet"

    p_rows4 = client.get("/api/portfolio").json()
    for item in p_rows4:
        assert item["pre_shares"] == 10.0
        assert item["current_shares"] == 10.0
