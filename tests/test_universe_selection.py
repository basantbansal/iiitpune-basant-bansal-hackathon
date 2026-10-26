import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
import pandas as pd

from src.api.main import app
from src.api.dependencies import AppState, get_state
from src.storage.db import SignalDatabase
from src.engine.catalog import get_catalog
from src.rebalancer.price_provider import PriceProvider

@pytest.fixture
def isolated_db(tmp_path):
    db_file = tmp_path / "test_universe.db"
    return SignalDatabase(str(db_file))

@pytest.fixture
def test_client(isolated_db):
    state = AppState(db=isolated_db)
    app.dependency_overrides[get_state] = lambda: state
    client = TestClient(app)
    yield client, state
    app.dependency_overrides.clear()

def test_get_universe_returns_all_20_instruments(test_client):
    """GET /api/universe returns all 20 catalog instruments with expected fields."""
    client, _ = test_client
    resp = client.get("/api/universe")
    assert resp.status_code == 200
    instruments = resp.json()
    assert isinstance(instruments, list)
    assert len(instruments) == 20

    us_insts = [i for i in instruments if i["market"] == "US"]
    in_insts = [i for i in instruments if i["market"] == "IN"]
    assert len(us_insts) == 10
    assert len(in_insts) == 10

    for inst in instruments:
        assert "id" in inst
        assert "display_ticker" in inst
        assert "name" in inst
        assert "market" in inst
        assert "exchange" in inst
        assert "currency" in inst
        assert "sector" in inst
        assert "provider_symbol" in inst

def test_get_universe_selection_default(test_client):
    """GET /api/universe/selection initially returns the default 10 US stocks."""
    client, state = test_client
    resp = client.get("/api/universe/selection")
    assert resp.status_code == 200
    data = resp.json()
    assert "selection" in data
    assert "default_selection" in data
    assert len(data["selection"]) == 10
    assert len(data["default_selection"]) == 10

    catalog = get_catalog()
    expected_default = list(catalog.get_default_selection_ids())
    assert data["selection"] == expected_default
    assert data["default_selection"] == expected_default

    for inst in data["selected_instruments"]:
        assert inst["market"] == "US"
        assert inst["currency"] == "USD"

def test_put_universe_selection_valid_mixed_market(test_client):
    """PUT /api/universe/selection accepts valid mixed US and Indian selections."""
    client, state = test_client
    mixed_ids = [
        "US_AAPL", "US_MSFT", "US_NVDA", "US_AMZN", "US_GOOGL",
        "IN_RELIANCE", "IN_TCS", "IN_HDFCBANK", "IN_INFY", "IN_ICICIBANK"
    ]

    resp = client.put("/api/universe/selection", json={"selection": mixed_ids})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["selection"] == mixed_ids

    # GET confirms update
    get_resp = client.get("/api/universe/selection")
    assert get_resp.status_code == 200
    assert get_resp.json()["selection"] == mixed_ids

    # Verify portfolio endpoint returns the active 10 stocks
    port_resp = client.get("/api/portfolio")
    assert port_resp.status_code == 200
    port_items = port_resp.json()
    assert len(port_items) == 10
    tickers = [p["ticker"] for p in port_items]
    assert "AAPL" in tickers
    assert "RELIANCE" in tickers
    assert "TCS" in tickers
    assert "XOM" not in tickers

    # Verify currency disclosure
    rel_item = next(p for p in port_items if p["ticker"] == "RELIANCE")
    assert rel_item["currency"] == "INR"
    assert rel_item["currency_symbol"] == "₹"
    assert rel_item["market"] == "IN"

    aapl_item = next(p for p in port_items if p["ticker"] == "AAPL")
    assert aapl_item["currency"] == "USD"
    assert aapl_item["currency_symbol"] == "$"
    assert aapl_item["market"] == "US"

def test_put_universe_selection_all_indian(test_client):
    """PUT /api/universe/selection accepts 10 Indian NSE stocks."""
    client, state = test_client
    in_ids = [
        "IN_RELIANCE", "IN_TCS", "IN_HDFCBANK", "IN_INFY", "IN_ICICIBANK",
        "IN_HINDUNILVR", "IN_ITC", "IN_BHARTIARTL", "IN_LT", "IN_SBIN"
    ]
    resp = client.put("/api/universe/selection", json=in_ids)
    assert resp.status_code == 200

    port_resp = client.get("/api/portfolio")
    port_items = port_resp.json()
    assert len(port_items) == 10
    for item in port_items:
        assert item["market"] == "IN"
        assert item["currency"] == "INR"
        assert item["currency_symbol"] == "₹"

def test_put_universe_selection_rejects_fewer_than_10(test_client):
    """PUT /api/universe/selection rejects selections with fewer than 10 stocks."""
    client, _ = test_client
    nine_ids = [
        "US_AAPL", "US_MSFT", "US_NVDA", "US_AMZN", "US_GOOGL",
        "US_META", "US_TSLA", "US_JPM", "US_JNJ"
    ]
    resp = client.put("/api/universe/selection", json={"selection": nine_ids})
    assert resp.status_code == 400
    assert "exactly 10 instruments" in resp.json()["detail"]

def test_put_universe_selection_rejects_more_than_10(test_client):
    """PUT /api/universe/selection rejects selections with more than 10 stocks."""
    client, _ = test_client
    eleven_ids = [
        "US_AAPL", "US_MSFT", "US_NVDA", "US_AMZN", "US_GOOGL",
        "US_META", "US_TSLA", "US_JPM", "US_JNJ", "US_XOM", "IN_RELIANCE"
    ]
    resp = client.put("/api/universe/selection", json={"selection": eleven_ids})
    assert resp.status_code == 400
    assert "exactly 10 instruments" in resp.json()["detail"]

def test_put_universe_selection_rejects_duplicates(test_client):
    """PUT /api/universe/selection rejects duplicate IDs."""
    client, _ = test_client
    dup_ids = [
        "US_AAPL", "US_AAPL", "US_NVDA", "US_AMZN", "US_GOOGL",
        "US_META", "US_TSLA", "US_JPM", "US_JNJ", "US_XOM"
    ]
    resp = client.put("/api/universe/selection", json={"selection": dup_ids})
    assert resp.status_code == 400
    assert "duplicate" in resp.json()["detail"].lower()

def test_put_universe_selection_rejects_unknown_ids(test_client):
    """PUT /api/universe/selection rejects unknown instrument IDs."""
    client, _ = test_client
    invalid_ids = [
        "US_AAPL", "US_MSFT", "US_NVDA", "US_AMZN", "US_GOOGL",
        "US_META", "US_TSLA", "US_JPM", "US_JNJ", "UNKNOWN_STOCK_XYZ"
    ]
    resp = client.put("/api/universe/selection", json={"selection": invalid_ids})
    assert resp.status_code == 400
    assert "unknown instrument" in resp.json()["detail"].lower()

def test_universe_selection_persistence_across_app_restart(isolated_db):
    """Selection is saved in SQLite and survives application/state restart."""
    state1 = AppState(db=isolated_db)
    mixed_ids = [
        "US_AAPL", "US_MSFT", "US_NVDA", "US_AMZN", "US_GOOGL",
        "IN_RELIANCE", "IN_TCS", "IN_HDFCBANK", "IN_INFY", "IN_ICICIBANK"
    ]
    state1.set_universe_selection(mixed_ids)

    # Simulate restart by creating state2 with same DB
    state2 = AppState(db=isolated_db)
    assert state2.selected_ids == mixed_ids
    assert "RELIANCE" in state2.rebalancer.tickers
    assert "AAPL" in state2.rebalancer.tickers
    assert "XOM" not in state2.rebalancer.tickers

def test_selected_universe_reaches_rebalancing_workflow(test_client):
    """Tactical rebalancer processes news signals for selected Indian & US constituents."""
    client, state = test_client
    mixed_ids = [
        "US_AAPL", "US_MSFT", "US_NVDA", "US_AMZN", "US_GOOGL",
        "IN_RELIANCE", "IN_TCS", "IN_HDFCBANK", "IN_INFY", "IN_ICICIBANK"
    ]
    client.put("/api/universe/selection", json={"selection": mixed_ids})

    signals = [
        {"entity": "NVDA", "sentiment_score": 0.8, "impact_score": 8, "event_classification": "Product Launch"},
        {"entity": "RELIANCE", "sentiment_score": -0.7, "impact_score": 8, "event_classification": "Credit Event"},
    ]

    mock_prices = {
        "AAPL": 150.0, "MSFT": 400.0, "NVDA": 120.0, "AMZN": 180.0, "GOOGL": 170.0,
        "RELIANCE": 1250.0, "TCS": 3500.0, "HDFCBANK": 1600.0, "INFY": 1800.0, "ICICIBANK": 1200.0
    }
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value=mock_prices):
        orders_df = state.rebalancer.rebalance(signals)
        assert not orders_df.empty
        tickers_in_orders = list(orders_df["Ticker"])
        assert "RELIANCE" in tickers_in_orders
        assert "NVDA" in tickers_in_orders

        rel_row = orders_df[orders_df["Ticker"] == "RELIANCE"].iloc[0]
        nvda_row = orders_df[orders_df["Ticker"] == "NVDA"].iloc[0]
        assert rel_row["Action"] == "SELL"
        assert nvda_row["Action"] == "BUY"

def test_fallback_price_safeguards_with_dual_market(test_client):
    """Fallback reference prices clearly disclose fallback status and currency without leaking into live execution."""
    client, state = test_client
    mixed_ids = [
        "US_AAPL", "US_MSFT", "US_NVDA", "US_AMZN", "US_GOOGL",
        "IN_RELIANCE", "IN_TCS", "IN_HDFCBANK", "IN_INFY", "IN_ICICIBANK"
    ]
    client.put("/api/universe/selection", json={"selection": mixed_ids})

    # With no live price download, price metadata discloses fallback status
    meta = state.rebalancer.price_provider.get_prices_with_metadata(state.rebalancer.tickers)
    assert meta["any_fallback"] is True

    rel_meta = meta["constituents"]["RELIANCE"]
    assert rel_meta["is_fallback"] is True
    assert rel_meta["currency"] == "INR"
    assert "₹" in rel_meta["source"]

    aapl_meta = meta["constituents"]["AAPL"]
    assert aapl_meta["is_fallback"] is True
    assert aapl_meta["currency"] == "USD"
    assert "$" in aapl_meta["source"]

    # require_live_prices strictly raises RuntimeError if live market quote missing
    with pytest.raises(RuntimeError, match="Verified live market quotes unavailable"):
        state.rebalancer.price_provider.require_live_prices(["RELIANCE", "AAPL"])
