import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import pandas as pd

from src.api.main import app
from src.api.dependencies import AppState, get_state
from src.storage.db import SignalDatabase
from src.engine.catalog import get_catalog
from src.rebalancer.fx_provider import FXRateProvider, FXRate
from src.rebalancer.price_provider import PriceProvider

@pytest.fixture
def isolated_db(tmp_path):
    db_file = tmp_path / "test_multicurrency.db"
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


def test_1_usd_only_portfolio_nav_and_cash(test_client):
    """Rule 2, 3 & 5: Explicit reporting currency (USD), separate cash balances, USD-only NAV."""
    client, state = test_client
    prices = {t: 100.0 for t in state.rebalancer.tickers}

    with patch.object(state.rebalancer, "fetch_current_prices", return_value=prices), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        metrics = client.get("/api/portfolio/metrics").json()
        assert metrics["reporting_currency"] == "USD"
        assert metrics["cash_usd"] == pytest.approx(990000.0, abs=1.0)
        assert metrics["cash_inr"] == 0.0
        assert metrics["cash_inr_usd_equiv"] == 0.0
        assert metrics["holdings_market_value_usd"] == pytest.approx(10000.0, abs=1.0)
        assert metrics["holdings_market_value_inr"] == 0.0
        assert metrics["holdings_market_value"] == pytest.approx(10000.0, abs=1.0)
        assert metrics["total_value"] == pytest.approx(1000000.0, abs=1.0)


def test_2_inr_only_portfolio_nav_with_live_fx(test_client):
    """Rule 4 & 5: INR-only portfolio with verified live FX rate (85.00 INR per USD)."""
    client, state = test_client
    catalog = get_catalog()

    # Switch universe to India-only
    client.put("/api/universe/selection", json={"selection": IN_10_IDS})

    # Mock market prices for all 10 Indian constituents at ₹1,000 each (10 sh each = ₹10,000 each -> ₹100,000 total)
    in_tickers = [catalog.get_by_id(i_id).display_ticker for i_id in IN_10_IDS]
    prices = {t: 1000.0 for t in in_tickers}
    state.rebalancer.price_provider._prices.update(prices)

    live_fx = FXRate(
        base_currency="USD", quote_currency="INR", rate=85.00,
        as_of="2026-10-15T12:00:00Z", source="Yahoo Finance USDINR=X",
        is_fallback=False, observation_time="2026-10-15T12:00:00Z", is_stale=False
    )
    with patch.object(state.fx_provider, "get_rate", return_value=live_fx), \
         patch.object(state.rebalancer, "fetch_current_prices", return_value=prices):
        alloc_res = state.allocate_capital(usd_amount=500000.0, inr_amount_usd=500000.0)
        assert alloc_res["allocated_inr"] == pytest.approx(500000.0 * 85.00, abs=1.0)
        assert alloc_res["cash_balances"]["INR"] == pytest.approx(42500000.0 - 100000.0, abs=1.0)

        with patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
            metrics = client.get("/api/portfolio/metrics").json()
            assert metrics["reporting_currency"] == "USD"
            assert metrics["nav_status"] == "LIVE"
            assert metrics["fx_rate"] == 85.00
            assert metrics["fx_rate_is_live"] is True
            assert metrics["fx_rate_is_fallback"] is False

            # Holdings: 10 stocks * 10 sh * 1,000 = ₹100,000 INR
            assert metrics["holdings_market_value_inr"] == pytest.approx(100000.0, abs=1.0)
            expected_holdings_usd = round(100000.0 / 85.00, 2)
            assert metrics["holdings_market_value_inr_usd_equiv"] == pytest.approx(expected_holdings_usd, abs=0.05)

            # Cash: $500,000 USD, and (500,000 * 85 - 100,000) INR
            assert metrics["cash_usd"] == pytest.approx(500000.0, abs=1.0)
            assert metrics["cash_inr"] == pytest.approx(42500000.0 - 100000.0, abs=1.0)
            expected_cash_inr_usd = round((42500000.0 - 100000.0) / 85.00, 2)
            assert metrics["cash_inr_usd_equiv"] == pytest.approx(expected_cash_inr_usd, abs=0.05)

            # Total consolidated NAV: 500,000 + expected_cash_inr_usd + expected_holdings_usd = 1,000,000 USD
            assert metrics["total_value"] == pytest.approx(1000000.0, abs=1.0)


def test_3_mixed_market_portfolio_nav_mathematical_reconciliation(test_client):
    """Rule 5 & 10: Mixed-market portfolio (5 US, 5 IN) mathematical NAV identity reconciliation."""
    client, state = test_client
    catalog = get_catalog()

    # Switch to mixed universe
    client.put("/api/universe/selection", json={"selection": MIXED_10_IDS})

    live_fx = FXRate(
        base_currency="USD", quote_currency="INR", rate=80.00,
        as_of="2026-10-15T12:00:00Z", source="Yahoo Finance USDINR=X",
        is_fallback=False, observation_time="2026-10-15T12:00:00Z", is_stale=False
    )
    with patch.object(state.fx_provider, "get_rate", return_value=live_fx):
        # Explicitly allocate 50% US ($500k), 50% IN ($500k * 80 = ₹40,000,000)
        state.allocate_capital(usd_ratio=0.5, inr_ratio=0.5)

        # US stocks: $100 each (10 sh * 5 = $5,000)
        # IN stocks: ₹2,000 each (10 sh * 5 = ₹100,000)
        def mock_prices(*args, **kwargs):
            return {
                t: 2000.0 if (catalog.get_by_ticker(t) and catalog.get_by_ticker(t).currency == "INR") else 100.0
                for t in state.rebalancer.tickers
            }

        with patch.object(state.rebalancer, "fetch_current_prices", side_effect=mock_prices), \
             patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
            metrics = client.get("/api/portfolio/metrics").json()
            assert metrics["nav_status"] == "LIVE"

            holdings_usd = metrics["holdings_market_value_usd"]
            holdings_inr = metrics["holdings_market_value_inr"]
            cash_usd = metrics["cash_usd"]
            cash_inr = metrics["cash_inr"]
            fx_rate = metrics["fx_rate"]
            nav = metrics["total_value"]

            assert holdings_usd == pytest.approx(5000.0, abs=1.0)
            assert holdings_inr == pytest.approx(100000.0, abs=1.0)
            assert fx_rate == 80.00

            # Mathematical Identity:
            # NAV = Cash_USD + (Cash_INR / Rate) + Holdings_USD + (Holdings_INR / Rate)
            reconciled_nav = cash_usd + (cash_inr / fx_rate) + holdings_usd + (holdings_inr / fx_rate)
            assert nav == pytest.approx(reconciled_nav, abs=0.1)
            assert nav == pytest.approx(1000000.0, abs=1.0)


def test_4_fx_rate_changes_dynamically_revalue_portfolio(test_client):
    """Rule 4 & 10: Dynamic NAV sensitivity to FX rate fluctuations."""
    client, state = test_client
    catalog = get_catalog()

    client.put("/api/universe/selection", json={"selection": MIXED_10_IDS})

    def mock_prices(*args, **kwargs):
        return {t: 2000.0 if (catalog.get_by_ticker(t) and catalog.get_by_ticker(t).currency == "INR") else 100.0 for t in state.rebalancer.tickers}

    # At 1 USD = 80.00 INR
    fx_80 = FXRate(
        base_currency="USD", quote_currency="INR", rate=80.00,
        as_of="2026-10-15T10:00:00Z", source="Yahoo Finance",
        is_fallback=False, observation_time="2026-10-15T10:00:00Z", is_stale=False
    )
    with patch.object(state.fx_provider, "get_rate", return_value=fx_80), \
         patch.object(state.rebalancer, "fetch_current_prices", side_effect=mock_prices), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        m1 = client.get("/api/portfolio/metrics").json()
        assert m1["fx_rate"] == 80.00
        # ₹100,000 INR holdings at 80.00 = $1,250.00 USD
        assert m1["holdings_market_value_inr_usd_equiv"] == pytest.approx(1250.00, abs=0.05)

    # When INR depreciates: 1 USD = 100.00 INR
    fx_100 = FXRate(
        base_currency="USD", quote_currency="INR", rate=100.00,
        as_of="2026-10-15T11:00:00Z", source="Yahoo Finance",
        is_fallback=False, observation_time="2026-10-15T11:00:00Z", is_stale=False
    )
    with patch.object(state.fx_provider, "get_rate", return_value=fx_100), \
         patch.object(state.rebalancer, "fetch_current_prices", side_effect=mock_prices), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        m2 = client.get("/api/portfolio/metrics").json()
        assert m2["fx_rate"] == 100.00
        # ₹100,000 INR holdings at 100.00 = $1,000.00 USD (exact $250 drop)
        assert m2["holdings_market_value_inr_usd_equiv"] == pytest.approx(1000.00, abs=0.05)
        diff = m1["holdings_market_value_inr_usd_equiv"] - m2["holdings_market_value_inr_usd_equiv"]
        assert diff == pytest.approx(250.00, abs=0.1)


def test_5_missing_or_stale_fx_makes_nav_unavailable(test_client):
    """Rule 5: When FX rate is stale or fallback, consolidated NAV is strictly reported as UNAVAILABLE."""
    client, state = test_client
    catalog = get_catalog()

    # Switch to India-only
    client.put("/api/universe/selection", json={"selection": IN_10_IDS})

    # Default FX provider has fallback rate with is_fallback=True and is_stale=True
    stale_fx = FXRate(
        base_currency="USD", quote_currency="INR", rate=84.00,
        as_of="2026-01-01T00:00:00Z", source="Deterministic Fallback",
        is_fallback=True, observation_time="2026-01-01T00:00:00Z", is_stale=True
    )
    prices = {t: 1000.0 for t in state.rebalancer.tickers}
    state.rebalancer.price_provider._prices.update(prices)
    with patch.object(state.fx_provider, "get_rate", return_value=stale_fx), \
         patch.object(state.rebalancer, "fetch_current_prices", return_value=prices), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        metrics = client.get("/api/portfolio/metrics").json()
        assert metrics["nav_status"] == "UNAVAILABLE"
        assert metrics["total_value"] is None
        assert metrics["holdings_market_value"] is None
        assert "stale or fallback-only" in metrics["nav_unavailability_reason"]
        # Indicative NAV is provided for transparency
        assert metrics["indicative_nav_usd"] is not None


def test_6_missing_constituent_price_makes_nav_unavailable(test_client):
    """Rule 5: If any constituent live price is missing (None), NAV is UNAVAILABLE with explicit reason."""
    client, state = test_client

    # Missing price for AAPL
    partial_prices = {t: (100.0 if t != "AAPL" else None) for t in state.rebalancer.tickers}
    with patch.object(state.rebalancer, "fetch_current_prices", return_value=partial_prices), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        metrics = client.get("/api/portfolio/metrics").json()
        assert metrics["nav_status"] == "UNAVAILABLE"
        assert metrics["total_value"] is None
        assert "AAPL" in metrics["nav_unavailability_reason"]


def test_7_fee_accounting_native_and_usd(test_client):
    """Rule 6 & 10: 10 bps transaction fees calculated and stored in native currency and USD equivalent."""
    client, state = test_client

    # Simulate orders: 1 US trade of $10,000, 1 Indian trade of ₹80,000
    mock_orders = pd.DataFrame([
        {
            "Ticker": "AAPL", "Currency": "USD", "Action": "BUY", "Order Qty": 100.0,
            "Trade Value (Native)": 10000.0, "Trade Value ($)": 10000.0,
            "Est Fee (Native)": 10.0, "Est Fee ($)": 10.0,
            "Price ($)": 100.0, "Price (Native)": 100.0,
            "Current Shares": 10.0, "Pre Shares": 10.0, "Target Shares": 110.0, "Post Shares": 110.0,
            "Signed Qty": 100.0, "Prev Weight": "10.00%", "New Weight": "15.00%", "Delta": "+5.00%",
            "Is Executable": True, "Execution Status": "EXECUTABLE"
        },
        {
            "Ticker": "RELIANCE", "Currency": "INR", "Action": "BUY", "Order Qty": 40.0,
            "Trade Value (Native)": 80000.0, "Trade Value ($)": 1000.0, # at 80.0 rate
            "Est Fee (Native)": 80.0, "Est Fee ($)": 1.0,
            "Price ($)": 25.0, "Price (Native)": 2000.0,
            "Current Shares": 10.0, "Pre Shares": 10.0, "Target Shares": 50.0, "Post Shares": 50.0,
            "Signed Qty": 40.0, "Prev Weight": "10.00%", "New Weight": "15.00%", "Delta": "+5.00%",
            "Is Executable": True, "Execution Status": "EXECUTABLE"
        }
    ])
    state.latest_orders = mock_orders

    live_fx = FXRate(
        base_currency="USD", quote_currency="INR", rate=80.00,
        as_of="2026-10-15T12:00:00Z", source="Yahoo Finance",
        is_fallback=False, observation_time="2026-10-15T12:00:00Z", is_stale=False
    )
    with patch.object(state.fx_provider, "get_rate", return_value=live_fx), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        metrics = client.get("/api/portfolio/metrics").json()
        assert metrics["est_txn_cost_usd"] == pytest.approx(10.0, abs=0.01)
        assert metrics["est_txn_cost_inr"] == pytest.approx(80.0, abs=0.01)
        # Total USD fees = $10.00 + (₹80.00 / 80.0) = $11.00
        assert metrics["est_txn_cost"] == pytest.approx(11.00, abs=0.01)


def test_8_insufficient_currency_cash_withholds_trade(test_client):
    """Rule 3 & 7: Trades are withheld if currency-specific cash balance is insufficient."""
    client, state = test_client
    catalog = get_catalog()

    # Switch to mixed universe so RELIANCE is included
    client.put("/api/universe/selection", json={"selection": MIXED_10_IDS})

    # Cash balances: USD $500k, but INR cash is 0
    state.cash_balances = {"USD": 500000.0, "INR": 0.0}

    # Signal to buy RELIANCE (INR stock)
    signals = [{"entity": "RELIANCE", "sentiment_score": 0.9, "impact_score": 8, "event_classification": "Product Launch"}]

    prices = {t: 2000.0 if (catalog.get_by_ticker(t) and catalog.get_by_ticker(t).currency == "INR") else 100.0 for t in state.rebalancer.tickers}
    state.rebalancer.price_provider._prices.update(prices)

    live_fx = FXRate(
        base_currency="USD", quote_currency="INR", rate=80.00,
        as_of="2026-10-15T12:00:00Z", source="Yahoo Finance",
        is_fallback=False, observation_time="2026-10-15T12:00:00Z", is_stale=False
    )
    with patch.object(state.fx_provider, "get_rate", return_value=live_fx), \
         patch.object(state.rebalancer, "fetch_current_prices", return_value=prices):
        # Rebalancer with cash_balances check
        df = state.rebalancer.rebalance(signals, cash_balances=state.cash_balances, require_live=True)
        reliance_row = df[df["Ticker"] == "RELIANCE"].iloc[0]

        # Because INR cash is 0.0, buy order cannot execute! Action must be HOLD
        assert reliance_row["Action"] == "HOLD"
        assert reliance_row["Order Qty"] == 0.0
        assert reliance_row["Execution Status"] == "WITHHELD_INSUFFICIENT_CASH"
        assert bool(reliance_row["Is Executable"]) is False

        # USD cash must not be drawn down
        assert state.cash_balances["USD"] == 500000.0


def test_9_explicit_fx_conversion_and_audit_logging(test_client, isolated_db):
    """Rule 4 & 8: Explicit currency conversion endpoint and SQLite audit logging."""
    client, state = test_client

    state.cash_balances = {"USD": 1000000.0, "INR": 0.0}
    isolated_db.save_cash_balances(state.cash_balances)

    live_fx = FXRate(
        base_currency="USD", quote_currency="INR", rate=84.50,
        as_of="2026-10-15T12:00:00Z", source="Yahoo Finance Live",
        is_fallback=False, observation_time="2026-10-15T12:00:00Z", is_stale=False
    )
    with patch.object(state.fx_provider, "get_rate", return_value=live_fx):
        # Convert $200,000 USD to INR
        res = client.post("/api/portfolio/convert-fx", json={
            "from_currency": "USD",
            "to_currency": "INR",
            "amount": 200000.0,
            "notes": "Funding Indian equities account"
        })
        assert res.status_code == 200
        data = res.json()["conversion"]
        assert data["from_amount"] == 200000.0
        assert data["to_amount"] == pytest.approx(200000.0 * 84.50, abs=1.0)
        assert data["rate"] == 84.50
        assert data["is_live"] is True

        # Check in-memory cash balances
        assert state.cash_usd == pytest.approx(800000.0, abs=1.0)
        assert state.cash_inr == pytest.approx(16900000.0, abs=1.0)

        # Check SQLite audit log
        history_res = client.get("/api/portfolio/fx-conversions")
        assert history_res.status_code == 200
        history = history_res.json()["conversions"]
        assert len(history) == 1
        assert history[0]["from_currency"] == "USD"
        assert history[0]["to_currency"] == "INR"
        assert history[0]["from_amount"] == 200000.0
        assert history[0]["to_amount"] == pytest.approx(16900000.0, abs=1.0)

        # Attempting conversion exceeding available cash must fail with 400
        fail_res = client.post("/api/portfolio/convert-fx", json={
            "from_currency": "USD",
            "to_currency": "INR",
            "amount": 900000.0
        })
        assert fail_res.status_code == 400
        assert "Insufficient USD cash" in fail_res.json()["detail"]


def test_10_market_switching_and_persistence_across_appstate_reload(test_client, isolated_db):
    """Rule 1 & 10: State persistence across universe switching and AppState restart."""
    client, state = test_client

    # 1. Start US, allocate and customize AAPL to 40 shares
    custom = {t: 10.0 for t in state.rebalancer.tickers}
    custom["AAPL"] = 40.0
    client.post("/api/portfolio/holdings", json={"holdings": custom})

    # 2. Convert $100,000 USD to INR
    live_fx = FXRate(
        base_currency="USD", quote_currency="INR", rate=84.00,
        as_of="2026-10-15T12:00:00Z", source="Yahoo Finance",
        is_fallback=False, observation_time="2026-10-15T12:00:00Z", is_stale=False
    )
    with patch.object(state.fx_provider, "get_rate", return_value=live_fx):
        state.execute_fx_conversion("USD", "INR", 100000.0)

    # 3. Switch to Mixed universe (retains AAPL)
    client.put("/api/universe/selection", json={"selection": MIXED_10_IDS})

    # Retained AAPL has 40 shares
    assert state.rebalancer.current_shares["AAPL"] == 40.0
    assert state.cash_inr == pytest.approx(8400000.0, abs=1.0)

    # 4. Simulate complete server restart with same SQLite database
    reloaded_state = AppState(db=isolated_db)
    assert reloaded_state.rebalancer.current_shares["AAPL"] == 40.0
    assert reloaded_state.cash_inr == pytest.approx(8400000.0, abs=1.0)
    assert reloaded_state.cash_usd == pytest.approx(state.cash_usd, abs=1.0)
    assert set(reloaded_state.selected_ids) == set(MIXED_10_IDS)


def test_11_target_weights_cross_universe_resilience(isolated_db):
    """Regression test: Target weights from an alternate universe do not cause KeyError when switching or reloading AppState."""
    # 1. Save weights for 10 Indian constituents
    cat = get_catalog()
    in_tickers = [cat.get_by_id(i).display_ticker for i in IN_10_IDS]
    in_weights = {t: 0.10 for t in in_tickers}
    isolated_db.save_target_weights_history("2026-10-15T10:00:00Z", in_weights)
    
    # 2. Select default 10 US stocks
    isolated_db.save_universe_selection(US_10_IDS)
    
    # 3. Initialize AppState - must not crash with KeyError for US constituents missing from in_weights
    state = AppState(db=isolated_db)
    us_tickers = [cat.get_by_id(i).display_ticker for i in US_10_IDS]
    for t in us_tickers:
        assert t in state.rebalancer.current_weights
        assert state.rebalancer.current_weights[t] == pytest.approx(0.10, abs=1e-4)
    
    # 4. Rebalance calculation must run without KeyError
    signals = [{"entity": "AAPL", "sentiment_score": 0.5, "impact_score": 6, "event_classification": "Product Launch"}]
    df = state.rebalancer.rebalance(signals)
    assert not df.empty
    assert "AAPL" in df["Ticker"].values

