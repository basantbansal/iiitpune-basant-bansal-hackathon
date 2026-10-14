import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
import math
import pandas as pd

from src.api.main import app
from src.api.dependencies import AppState, get_state
from src.storage.db import SignalDatabase


@pytest.fixture
def isolated_db(tmp_path):
    db_file = tmp_path / "test_holdings.db"
    return SignalDatabase(str(db_file))


@pytest.fixture
def mock_prices():
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    return {t: 100.0 for t in tickers}


def test_holdings_valid_update(isolated_db, mock_prices):
    """Valid whole-number non-negative shares within budget update state and database."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value=mock_prices), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        state = AppState(db=isolated_db)
        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        # 500 shares each across 10 stocks @ $100 = $50,000 * 10 = $500,000 (within $1,000,000 budget)
        new_holdings = {t: 500.0 for t in state.rebalancer.tickers}
        resp = client.post("/api/portfolio/holdings", json={"holdings": new_holdings})
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["total_invested"] == 500000.0
        assert data["remaining_cash"] == 500000.0
        assert data["initial_capital"] == 1000000.0
        for t in state.rebalancer.tickers:
            assert data["holdings"][t] == 500.0

        # State memory is updated
        assert state.rebalancer.current_shares["AAPL"] == 500.0
        # Orders are cleared (holding update is not a trade)
        assert state.latest_orders.empty


def test_holdings_zero_shares_supported(isolated_db, mock_prices):
    """Zero shares for some constituents must be valid."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value=mock_prices), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        state = AppState(db=isolated_db)
        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        new_holdings = {t: 0.0 for t in state.rebalancer.tickers}
        new_holdings["AAPL"] = 1000.0  # $100,000 invested, rest 0
        resp = client.post("/api/portfolio/holdings", json={"holdings": new_holdings})
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["holdings"]["AAPL"] == 1000.0
        assert data["holdings"]["MSFT"] == 0.0
        assert data["total_invested"] == 100000.0
        assert data["remaining_cash"] == 900000.0


def test_holdings_negative_shares_rejected(isolated_db, mock_prices):
    """Negative share quantities must be rejected with HTTP 400."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value=mock_prices):
        state = AppState(db=isolated_db)
        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        invalid_holdings = {t: 100.0 for t in state.rebalancer.tickers}
        invalid_holdings["TSLA"] = -50.0
        resp = client.post("/api/portfolio/holdings", json={"holdings": invalid_holdings})
        app.dependency_overrides.clear()

        assert resp.status_code == 400
        assert "cannot be negative" in resp.json()["detail"]


def test_holdings_fractional_shares_rejected(isolated_db, mock_prices):
    """Fractional share quantities in editor must be rejected with HTTP 400."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value=mock_prices):
        state = AppState(db=isolated_db)
        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        invalid_holdings = {t: 100.0 for t in state.rebalancer.tickers}
        invalid_holdings["NVDA"] = 100.5
        resp = client.post("/api/portfolio/holdings", json={"holdings": invalid_holdings})
        app.dependency_overrides.clear()

        assert resp.status_code == 400
        assert "must be a whole number" in resp.json()["detail"]


def test_holdings_unknown_ticker_rejected(isolated_db, mock_prices):
    """Unknown ticker not part of index universe must be rejected with HTTP 400."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value=mock_prices):
        state = AppState(db=isolated_db)
        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        invalid_holdings = {t: 100.0 for t in state.rebalancer.tickers}
        invalid_holdings["UNKNOWN_XYZ"] = 100.0
        resp = client.post("/api/portfolio/holdings", json={"holdings": invalid_holdings})
        app.dependency_overrides.clear()

        assert resp.status_code == 400
        assert "Unknown constituent ticker" in resp.json()["detail"]


def test_holdings_over_budget_rejected(isolated_db, mock_prices):
    """Holdings whose market value exceeds available capital must be rejected with HTTP 400."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value=mock_prices):
        state = AppState(db=isolated_db)
        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        # 2,000 shares each @ $100 = $200,000 * 10 = $2,000,000 > $1,000,000 initial capital
        over_budget_holdings = {t: 2000.0 for t in state.rebalancer.tickers}
        resp = client.post("/api/portfolio/holdings", json={"holdings": over_budget_holdings})
        app.dependency_overrides.clear()

        assert resp.status_code == 400
        assert "exceeds available initial capital" in resp.json()["detail"]


def test_holdings_persists_across_app_restart(isolated_db, mock_prices):
    """Holdings saved via API must be loaded on a new AppState instance."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value=mock_prices):
        state1 = AppState(db=isolated_db)
        app.dependency_overrides[get_state] = lambda: state1
        client1 = TestClient(app)

        custom_holdings = {t: 700.0 for t in state1.rebalancer.tickers}
        custom_holdings["AAPL"] = 1200.0  # Total = 9*70,000 + 120,000 = 750,000 <= 1,000,000
        resp = client1.post("/api/portfolio/holdings", json={"holdings": custom_holdings})
        app.dependency_overrides.clear()
        assert resp.status_code == 200

        # Simulate restart with same DB
        state2 = AppState(db=isolated_db)
        for t in state2.rebalancer.tickers:
            expected = 1200.0 if t == "AAPL" else 700.0
            assert state2.rebalancer.current_shares[t] == pytest.approx(expected)


def test_reset_holdings_restores_equal_weight(isolated_db, mock_prices):
    """POST /api/portfolio/reset-holdings must restore equal-weight holdings."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value=mock_prices):
        state = AppState(db=isolated_db)
        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        # Change holdings first
        custom_holdings = {t: 100.0 for t in state.rebalancer.tickers}
        client.post("/api/portfolio/holdings", json={"holdings": custom_holdings})

        # Reset holdings
        resp = client.post("/api/portfolio/reset-holdings")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Default holdings reset to 10 shares per constituent
        for t in state.rebalancer.tickers:
            assert state.rebalancer.current_shares[t] == pytest.approx(10.0)


def test_subsequent_rebalance_after_holdings_update(isolated_db, mock_prices):
    """Subsequent scan after custom holdings updates rebalances from the customized baseline."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value=mock_prices), \
         patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news") as mock_news, \
         patch("src.engine.risk_engine.RiskEngine.analyze") as mock_analyze, \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):

        state = AppState(db=isolated_db)
        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        # Save customized holdings: 800 shares each ($80k each, total $800k)
        custom_holdings = {t: 800.0 for t in state.rebalancer.tickers}
        resp = client.post("/api/portfolio/holdings", json={"holdings": custom_holdings})
        assert resp.status_code == 200

        # Execute market scan with a bullish signal for AAPL
        mock_news.return_value = [{
            "headline": "Apple AAPL announces massive earnings beat and guidance increase",
            "source": "News",
            "published_at": "2026-10-13T10:00:00Z"
        }]

        class MockSig:
            def to_dict(self):
                return {
                    "entity": "AAPL",
                    "event_classification": "Earnings",
                    "sentiment_score": 0.8,
                    "impact_score": 9.0,
                    "confidence": 0.95,
                    "evidence_span": "record earnings",
                    "model_version": "v1.0"
                }
        mock_analyze.return_value = MockSig()

        scan_resp = client.post("/api/market-scan")
        app.dependency_overrides.clear()

        assert scan_resp.status_code == 200

        # Verify portfolio rebalance orders
        assert not state.latest_orders.empty
        aapl_order = state.latest_orders[state.latest_orders["Ticker"] == "AAPL"].iloc[0]
        # Current shares should reflect the saved 800.0 shares
        assert aapl_order["Current Shares"] == 800.0
        # Positive sentiment should tilt AAPL to BUY
        assert aapl_order["Action"] == "BUY"
        assert aapl_order["Order Qty"] > 0
        assert aapl_order["Target Shares"] > 800.0


def test_holdings_metrics_accounting_coherence(isolated_db, mock_prices):
    """Verify total portfolio value = holdings + cash, fees deducted once, and order math agrees."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value=mock_prices), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):

        state = AppState(db=isolated_db)
        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        # 600 shares per stock @ $100 = $60,000 * 10 = $600,000 invested; $400,000 cash
        custom_holdings = {t: 600.0 for t in state.rebalancer.tickers}
        save_resp = client.post("/api/portfolio/holdings", json={"holdings": custom_holdings})
        assert save_resp.status_code == 200

        # Check metrics endpoint
        metrics_resp = client.get("/api/portfolio/metrics")
        assert metrics_resp.status_code == 200
        m_data = metrics_resp.json()

        assert m_data["initial_capital"] == 1000000.0
        assert m_data["holdings_market_value"] == 600000.0
        assert m_data["cash_balance"] == 400000.0
        assert m_data["total_value"] == 1000000.0
        # Total value must strictly equal holdings + cash
        assert m_data["total_value"] == pytest.approx(m_data["holdings_market_value"] + m_data["cash_balance"])

        # Check portfolio items mathematical agreement
        p_resp = client.get("/api/portfolio")
        assert p_resp.status_code == 200
        p_data = p_resp.json()

        for item in p_data:
            assert item["pre_shares"] == 600.0
            assert item["target_shares"] == 600.0
            assert item["action"] == "HOLD"
            assert item["signed_qty"] == 0.0
            assert item["signed_delta_pct"] == 0.0
            assert item["trade_value"] == 0.0
            assert item["est_fee"] == 0.0
            # Target weight must match current weight when resting
            assert item["target_weight"] == pytest.approx(item["pre_weight"])
        app.dependency_overrides.clear()


def test_fresh_portfolio_initializes_with_affordable_shares(isolated_db):
    """Fresh portfolio must initialize with affordable shares within $1M budget using reference fallback."""
    # When price provider has no live prices (e.g. offline / startup)
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value={t: None for t in ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]}):
        state = AppState(db=isolated_db)
        assert len(state.rebalancer.current_shares) == 10
        for t, shares in state.rebalancer.current_shares.items():
            assert shares is not None
            assert shares > 0
            # 10 shares per constituent
            assert shares == pytest.approx(10.0)
        
        # Total market value across fallback reference prices strictly within $1,000,000
        total_val = sum(sh * 100.0 for sh in state.rebalancer.current_shares.values())
        assert total_val == 10000.0
        assert total_val <= 1000000.0


def test_full_lifecycle_save_refresh_reset_rescan(isolated_db, mock_prices):
    """End-to-end lifecycle: save custom holdings, reload state, reset, and re-scan preserves consistency."""
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices", return_value=mock_prices), \
         patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news") as mock_news, \
         patch("src.engine.risk_engine.RiskEngine.analyze") as mock_analyze, \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):

        # 1. Start session & save customized holdings: 700 shares each ($70,000 * 10 = $700,000, $300,000 cash)
        state1 = AppState(db=isolated_db)
        app.dependency_overrides[get_state] = lambda: state1
        client = TestClient(app)

        custom = {t: 700.0 for t in state1.rebalancer.tickers}
        save_resp = client.post("/api/portfolio/holdings", json={"holdings": custom})
        assert save_resp.status_code == 200

        # Check metrics immediately after save
        m1 = client.get("/api/portfolio/metrics").json()
        assert m1["holdings_market_value"] == 700000.0
        assert m1["cash_balance"] == 300000.0
        assert m1["total_value"] == 1000000.0
        assert m1["cash_balance"] >= 0.0

        # 2. Refresh / reload: instantiate state2 from the same DB
        state2 = AppState(db=isolated_db)
        app.dependency_overrides[get_state] = lambda: state2

        m2 = client.get("/api/portfolio/metrics").json()
        assert m2["holdings_market_value"] == 700000.0
        assert m2["cash_balance"] == 300000.0
        assert m2["total_value"] == 1000000.0
        assert state2.latest_orders.empty

        # 3. Reset data back to baseline benchmark
        reset_resp = client.post("/api/reset")
        assert reset_resp.status_code == 200
        assert reset_resp.json()["status"] == "ok"

        m3 = client.get("/api/portfolio/metrics").json()
        assert m3["cash_balance"] >= 0.0
        assert m3["total_value"] == 1000000.0

        # 4. Execute another market scan on the reset portfolio
        mock_news.return_value = [{
            "headline": "NVIDIA NVDA unveils groundbreaking next-gen Blackwell AI superchip",
            "source": "News",
            "published_at": "2026-10-13T12:00:00Z"
        }]

        class MockSig:
            def to_dict(self):
                return {
                    "entity": "NVDA",
                    "event_classification": "Product Launch",
                    "sentiment_score": 0.85,
                    "impact_score": 8.0,
                    "confidence": 0.90,
                    "evidence_span": "next-gen chip",
                    "model_version": "v1.0"
                }
        mock_analyze.return_value = MockSig()

        scan_resp = client.post("/api/market-scan")
        assert scan_resp.status_code == 200

        # Verify post-scan portfolio consistency
        m4 = client.get("/api/portfolio/metrics").json()
        assert m4["gross_turnover"] > 0
        assert m4["est_txn_cost"] > 0
        # Invariant: Total Value = Holdings + Cash (fees accounted exactly once)
        assert math.isclose(m4["holdings_market_value"] + m4["cash_balance"], m4["total_value"], abs_tol=1e-2)
        app.dependency_overrides.clear()

