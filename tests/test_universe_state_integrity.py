import pytest
import math
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import pandas as pd

from src.api.main import app
from src.api.dependencies import AppState, get_state
from src.storage.db import SignalDatabase
from src.engine.catalog import get_catalog
from src.rebalancer.price_provider import PriceProvider
from src.rebalancer.fx_provider import FXRateProvider

@pytest.fixture
def isolated_db(tmp_path):
    db_file = tmp_path / "test_integrity.db"
    return SignalDatabase(str(db_file))

@pytest.fixture
def test_client(isolated_db):
    state = AppState(db=isolated_db)
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


def test_scenario_1_universe_cycle_consistency(test_client, isolated_db):
    """
    Scenario 1: Cycle US-only -> India-only -> mixed-market -> US-only.
    Verify holdings, cash, target weights, portfolio metrics, and SQLite persistence.
    """
    client, state = test_client
    catalog = get_catalog()

    def mock_price_lookup(tickers):
        prices = {}
        for t in tickers:
            inst = catalog.get_by_ticker(t)
            if inst and inst.currency == "INR":
                prices[t] = 1200.0
            else:
                prices[t] = 100.0
        return prices

    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", side_effect=mock_price_lookup), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        # Step 1: Default US-only
        resp1 = client.get("/api/portfolio")
        assert resp1.status_code == 200
        items1 = resp1.json()
        assert len(items1) == 10
        assert set(p["ticker"] for p in items1) == set(catalog.get_by_id(i).display_ticker for i in US_10_IDS)
        assert state.cash_balance == pytest.approx(990000.0, abs=1.0) # 1,000,000 - 10 stocks * 10 sh * 100

        metrics1 = client.get("/api/portfolio/metrics").json()
        assert metrics1["initial_capital"] == 1000000.0
        assert metrics1["total_value"] == pytest.approx(1000000.0, abs=1.0)
        assert metrics1["holdings_market_value"] == pytest.approx(10000.0, abs=1.0)

        # Step 2: Switch to India-only
        put2 = client.put("/api/universe/selection", json={"selection": IN_10_IDS})
        assert put2.status_code == 200
        items2 = client.get("/api/portfolio").json()
        assert len(items2) == 10
        in_tickers = set(catalog.get_by_id(i).display_ticker for i in IN_10_IDS)
        assert set(p["ticker"] for p in items2) == in_tickers
        assert all(p["market"] == "IN" and p["currency"] == "INR" for p in items2)

        # In India-only, cash balance is purely USD cash reserves and must NOT subtract INR prices
        assert state.cash_balance == 1000000.0

        # In India-only, total_value and holdings_market_value must be null without cross-currency consolidation
        metrics2 = client.get("/api/portfolio/metrics").json()
        assert metrics2["total_value"] is None
        assert metrics2["holdings_market_value"] is None
        assert metrics2["cash_balance"] == 1000000.0

        # Step 3: Switch to mixed-market
        put3 = client.put("/api/universe/selection", json={"selection": MIXED_10_IDS})
        assert put3.status_code == 200
        items3 = client.get("/api/portfolio").json()
        assert len(items3) == 10
        mixed_tickers = set(catalog.get_by_id(i).display_ticker for i in MIXED_10_IDS)
        assert set(p["ticker"] for p in items3) == mixed_tickers

        # In mixed market (5 US, 5 IN), only 5 US stocks draw from USD cash (5 * 10 * 100 = $5,000)
        assert state.cash_balance == pytest.approx(995000.0, abs=1.0)
        metrics3 = client.get("/api/portfolio/metrics").json()
        assert metrics3["total_value"] is None
        assert metrics3["holdings_market_value"] is None
        assert metrics3["cash_balance"] == pytest.approx(995000.0, abs=1.0)

        # Step 4: Switch back to US-only
        put4 = client.put("/api/universe/selection", json={"selection": US_10_IDS})
        assert put4.status_code == 200
        items4 = client.get("/api/portfolio").json()
        assert len(items4) == 10
        us_tickers = set(catalog.get_by_id(i).display_ticker for i in US_10_IDS)
        assert set(p["ticker"] for p in items4) == us_tickers
        assert state.cash_balance == pytest.approx(990000.0, abs=1.0)
        metrics4 = client.get("/api/portfolio/metrics").json()
        assert metrics4["total_value"] == pytest.approx(1000000.0, abs=1.0)
        assert metrics4["holdings_market_value"] == pytest.approx(10000.0, abs=1.0)


def test_scenario_2_preserve_customized_shares_and_purge_removed_positions(test_client, isolated_db):
    """
    Scenario 2: Customize shares for AAPL and MSFT.
    Switch to mixed universe (retaining AAPL, MSFT, removing XOM, JNJ).
    Verify retained tickers keep customized shares; removed tickers leave NO stale positions, orders, or entries.
    """
    client, state = test_client

    # Customize holdings: AAPL=50, MSFT=25, all others 10
    custom_holdings = {t: 10 for t in state.rebalancer.tickers}
    custom_holdings["AAPL"] = 50
    custom_holdings["MSFT"] = 25

    up_resp = client.post("/api/portfolio/holdings", json={"holdings": custom_holdings})
    assert up_resp.status_code == 200

    # Switch to mixed market: AAPL & MSFT are retained, XOM & JNJ are removed, Indian stocks added
    resp = client.put("/api/universe/selection", json={"selection": MIXED_10_IDS})
    assert resp.status_code == 200

    # Retained tickers MUST preserve custom quantities
    assert state.rebalancer.current_shares["AAPL"] == 50.0
    assert state.rebalancer.current_shares["MSFT"] == 25.0
    # Newly added Indian constituents get default 10.0
    assert state.rebalancer.current_shares["RELIANCE"] == 10.0

    # Removed tickers must NOT be in current_shares
    assert "XOM" not in state.rebalancer.current_shares
    assert "JNJ" not in state.rebalancer.current_shares
    assert len(state.rebalancer.current_shares) == 10

    # Verify SQLite holdings table contains strictly the 10 active constituents
    db_holdings = isolated_db.get_holdings()
    assert "XOM" not in db_holdings
    assert "JNJ" not in db_holdings
    assert len(db_holdings) == 10
    assert db_holdings["AAPL"] == 50.0
    assert db_holdings["MSFT"] == 25.0

    # sync_holdings must NOT resurrect removed tickers
    state.sync_holdings()
    assert "XOM" not in state.rebalancer.current_shares
    assert len(state.rebalancer.current_shares) == 10

    # Simulate restart with same DB
    state_reloaded = AppState(db=isolated_db)
    assert len(state_reloaded.rebalancer.current_shares) == 10
    assert "XOM" not in state_reloaded.rebalancer.current_shares
    assert state_reloaded.rebalancer.current_shares["AAPL"] == 50.0


def test_scenario_3_cash_accounting_no_currency_commingling(test_client, isolated_db):
    """
    Scenario 3: Verify cash is calculated without subtracting INR prices from USD initial capital.
    Verify update_portfolio_holdings separates USD from INR and does not reject valid INR allocations.
    """
    client, state = test_client

    # Switch to India-only
    client.put("/api/universe/selection", json={"selection": IN_10_IDS})

    # Available cash must remain $1,000,000.00 USD
    assert state.cash_balance == 1000000.0

    # Update holdings with Indian stock positions (e.g. 100 shares of RELIANCE, 50 shares of TCS)
    # Reference prices: RELIANCE = 1200 INR, TCS = 2400 INR. Total INR value = 120,000 + 120,000 = 240,000 INR.
    in_holdings = {t: 10 for t in state.rebalancer.tickers}
    in_holdings["RELIANCE"] = 100
    in_holdings["TCS"] = 50

    resp = client.post("/api/portfolio/holdings", json={"holdings": in_holdings})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["total_invested"] == 0.0  # 0 USD invested
    assert data["remaining_cash"] == 1000000.0  # 1,000,000.0 USD cash intact

    # Verify metrics does not add INR stock value to USD cash
    metrics = client.get("/api/portfolio/metrics").json()
    assert metrics["total_value"] is None
    assert metrics["holdings_market_value"] is None
    assert metrics["cash_balance"] == 1000000.0


def test_scenario_4_unavailable_data_does_not_fabricate_executable_trades(test_client):
    """
    Scenario 4: When live prices are unavailable (or only fallback prices exist),
    rebalancer must NOT generate executable trades using fabricated prices.
    """
    client, state = test_client

    # In default offline or mock state where live price returns None
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value={t: None for t in state.rebalancer.tickers}):
        signals = [
            {"entity": "AAPL", "sentiment_score": 0.8, "impact_score": 8, "event_classification": "Product Launch"},
            {"entity": "MSFT", "sentiment_score": -0.8, "impact_score": 8, "event_classification": "Credit Event"}
        ]
        orders_df = state.rebalancer.rebalance(signals)
        assert not orders_df.empty
        # All actions must be HOLD with 0.0 order quantity and 0.0 trade value because price is unavailable
        assert all(row["Action"] == "HOLD" for _, row in orders_df.iterrows())
        assert all(row["Order Qty"] == 0.0 for _, row in orders_df.iterrows())
        assert all(row["Trade Value ($)"] == 0.0 for _, row in orders_df.iterrows())

    # require_live_prices strictly raises RuntimeError if live market quote missing
    with pytest.raises(RuntimeError, match="Verified live market quotes unavailable"):
        state.rebalancer.price_provider.require_live_prices(["AAPL", "RELIANCE"])

    # require_live_rate strictly raises RuntimeError if FX rate is a fallback
    fx_prov = FXRateProvider()
    with pytest.raises(RuntimeError, match="Live exchange rate unavailable"):
        fx_prov.require_live_rate("USD", "INR")


def test_scenario_5_pending_orders_cleared_on_universe_change(test_client, isolated_db):
    """
    Scenario 5: Pending simulated orders and fees must remain consistent after universe change.
    Prior universe orders must be cleared from memory and SQLite.
    """
    client, state = test_client

    # Populate state with pending simulated orders for US universe
    mock_orders = pd.DataFrame([
        {"Ticker": "AAPL", "Action": "BUY", "Order Qty": 10.0, "Trade Value ($)": 1500.0,
         "Prev Weight": "10.00%", "New Weight": "12.00%", "Delta": "+2.00%",
         "Current Shares": 10.0, "Pre Shares": 10.0, "Target Shares": 20.0, "Post Shares": 20.0, "Signed Qty": 10.0, "Price ($)": 150.0},
        {"Ticker": "MSFT", "Action": "SELL", "Order Qty": 5.0, "Trade Value ($)": 2000.0,
         "Prev Weight": "10.00%", "New Weight": "8.00%", "Delta": "-2.00%",
         "Current Shares": 10.0, "Pre Shares": 10.0, "Target Shares": 5.0, "Post Shares": 5.0, "Signed Qty": -5.0, "Price ($)": 400.0}
    ])
    state.latest_orders = mock_orders
    isolated_db.save_latest_orders(mock_orders)

    # Verify orders exist initially
    assert not isolated_db.get_latest_orders().empty

    # Switch universe to India-only
    client.put("/api/universe/selection", json={"selection": IN_10_IDS})

    # Orders must be cleared because constituent set changed and there are no India signals
    assert state.latest_orders.empty
    db_orders = isolated_db.get_latest_orders()
    assert db_orders.empty

    # Portfolio metrics must report 0 turnover and 0 trading fees
    metrics = client.get("/api/portfolio/metrics").json()
    assert metrics["total_turnover"] == 0.0
    assert metrics["est_txn_cost"] == 0.0
