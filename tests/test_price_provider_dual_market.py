import pytest
import math
import pandas as pd
from unittest.mock import patch, MagicMock
from src.rebalancer.price_provider import PriceProvider
from src.engine.catalog import get_catalog
from src.api.utils import fetch_portfolio_covariance

def make_mock_df(prices_dict):
    df = pd.DataFrame([prices_dict])
    df.index = pd.to_datetime(["2026-10-14"])
    return df

def test_symbol_resolution_via_catalog():
    """Verify PriceProvider resolves both US and Indian identifiers to valid provider symbols."""
    provider = PriceProvider()

    # US tickers
    assert provider._resolve_provider_symbol("AAPL") == "AAPL"
    assert provider._resolve_provider_symbol("US_AAPL") == "AAPL"
    assert provider._resolve_provider_symbol("MSFT") == "MSFT"

    # Indian tickers (including verified IN_SBIN)
    assert provider._resolve_provider_symbol("RELIANCE") == "RELIANCE.NS"
    assert provider._resolve_provider_symbol("IN_RELIANCE") == "RELIANCE.NS"
    assert provider._resolve_provider_symbol("TCS") == "TCS.NS"
    assert provider._resolve_provider_symbol("IN_INFY") == "INFY.NS"
    assert provider._resolve_provider_symbol("INFY") == "INFY.NS"
    assert provider._resolve_provider_symbol("SBIN") == "SBIN.NS"
    assert provider._resolve_provider_symbol("IN_SBIN") == "SBIN.NS"

    # Uncataloged test ticker preserved as-is
    assert provider._resolve_provider_symbol("CUSTOM_TICKER") == "CUSTOM_TICKER"

def test_us_and_indian_mocked_price_retrieval():
    """Verify PriceProvider retrieves mocked prices for both US and Indian assets without collisions."""
    provider = PriceProvider()

    # Mock yfinance to return prices indexed by provider symbols
    mock_data = {
        "AAPL": 220.0,
        "MSFT": 410.0,
        "RELIANCE.NS": 1250.0,
        "SBIN.NS": 950.0,
    }
    with patch("src.rebalancer.price_provider.yf.download", return_value=make_mock_df(mock_data)):
        # Refresh using a mix of display tickers and internal IDs
        provider.refresh_prices(["AAPL", "MSFT", "IN_RELIANCE", "SBIN"])

        # US prices
        assert provider.get_price("AAPL") == 220.0
        assert provider.get_price("US_AAPL") == 220.0
        assert provider.get_price("MSFT") == 410.0

        # Indian prices accessible by both display ticker and internal ID
        assert provider.get_price("IN_RELIANCE") == 1250.0
        assert provider.get_price("RELIANCE") == 1250.0
        assert provider.get_price("SBIN") == 950.0
        assert provider.get_price("IN_SBIN") == 950.0

def test_invalid_symbol_and_missing_asset_graceful_handling():
    """
    Verify PriceProvider returns None for unknown tickers, invalid numbers,
    and missing/delisted assets returning NaN.
    """
    provider = PriceProvider()

    mock_data = {
        "AAPL": 220.0,
        "DELISTED.NS": float("nan"),
        "INVALID_SYM": -50.0
    }
    with patch("src.rebalancer.price_provider.yf.download", return_value=make_mock_df(mock_data)):
        provider.refresh_prices(["AAPL", "DELISTED.NS", "UNKNOWN_TICKER", "INVALID_SYM"])

        assert provider.get_price("AAPL") == 220.0
        assert provider.get_price("DELISTED.NS") is None
        assert provider.get_price("UNKNOWN_TICKER") is None
        assert provider.get_price("INVALID_SYM") is None

def test_live_price_enforcement_and_require_live_prices():
    """
    Item 3: Ensure live-price-dependent operations cannot silently treat
    deterministic reference prices as live market quotes.
    """
    provider = PriceProvider()

    mock_data = {
        "AAPL": 225.0,
        "MSFT": 410.0
        # RELIANCE missing
    }
    with patch("src.rebalancer.price_provider.yf.download", return_value=make_mock_df(mock_data)):
        provider.refresh_prices(["AAPL", "MSFT", "IN_RELIANCE"])

        # get_live_price strictly returns float for live, None for missing
        assert provider.get_live_price("AAPL") == 225.0
        assert provider.get_live_price("MSFT") == 410.0
        assert provider.get_live_price("IN_RELIANCE") is None

        # require_live_prices raises RuntimeError if any constituent lacks a verified live price
        with pytest.raises(RuntimeError, match="Verified live market quotes unavailable for"):
            provider.require_live_prices(["AAPL", "MSFT", "IN_RELIANCE"])

        # require_live_prices succeeds when all requested assets are live
        live = provider.require_live_prices(["AAPL", "MSFT"])
        assert live == {"AAPL": 225.0, "MSFT": 410.0}

def test_fallback_metadata_discloses_currency_and_source():
    """
    Verify get_prices_with_metadata clearly reports fallback status,
    correct currency (USD vs INR), and reference price values.
    """
    provider = PriceProvider()

    # Refresh with empty data so all assets trigger fallback
    with patch("src.rebalancer.price_provider.yf.download", return_value=pd.DataFrame()):
        provider.refresh_prices(["US_AAPL", "IN_RELIANCE", "IN_SBIN"])

        meta = provider.get_prices_with_metadata(["US_AAPL", "IN_RELIANCE", "IN_SBIN"])
        assert meta["all_live"] is False
        assert meta["any_fallback"] is True

        # US fallback
        aapl_meta = meta["constituents"]["US_AAPL"]
        assert aapl_meta["is_fallback"] is True
        assert aapl_meta["currency"] == "USD"
        assert aapl_meta["price"] == 100.0
        assert "$" in aapl_meta["source"]

        # Indian fallback
        rel_meta = meta["constituents"]["IN_RELIANCE"]
        assert rel_meta["is_fallback"] is True
        assert rel_meta["currency"] == "INR"
        assert rel_meta["price"] == 1200.0
        assert "₹" in rel_meta["source"]

        sbin_meta = meta["constituents"]["IN_SBIN"]
        assert sbin_meta["is_fallback"] is True
        assert sbin_meta["currency"] == "INR"
        assert sbin_meta["price"] == 850.0
        assert "₹" in sbin_meta["source"]
        assert sbin_meta["as_of"] == "2026-01-01T00:00:00Z"
        assert aapl_meta["as_of"] == "2026-01-01T00:00:00Z"
        assert rel_meta["as_of"] == "2026-01-01T00:00:00Z"

def test_live_price_metadata_discloses_exchange():
    """Verify live price metadata correctly attributes exchange and sets is_fallback=False."""
    provider = PriceProvider()

    mock_data = {
        "AAPL": 225.50,
        "SBIN.NS": 955.00
    }
    with patch("src.rebalancer.price_provider.yf.download", return_value=make_mock_df(mock_data)):
        provider.refresh_prices(["AAPL", "SBIN"])

        meta = provider.get_prices_with_metadata(["AAPL", "SBIN"])
        assert meta["all_live"] is True
        assert meta["any_fallback"] is False

        aapl = meta["constituents"]["AAPL"]
        assert aapl["is_fallback"] is False
        assert aapl["price"] == 225.50
        assert aapl["currency"] == "USD"
        assert "NASDAQ" in aapl["source"]

        sbin = meta["constituents"]["SBIN"]
        assert sbin["is_fallback"] is False
        assert sbin["price"] == 955.00
        assert sbin["currency"] == "INR"
        assert "NSE" in sbin["source"]

def test_fetch_portfolio_covariance_dual_market():
    """
    Verify fetch_portfolio_covariance translates Indian tickers to provider symbols,
    computes covariance, and preserves the requested ticker column order.
    """
    dates = pd.date_range("2026-01-01", periods=10, freq="B")
    mock_df = pd.DataFrame({
        "AAPL": [150.0 + i for i in range(10)],
        "SBIN.NS": [800.0 + (i * 5) for i in range(10)]
    }, index=dates)

    with patch("src.api.utils.yf.download", return_value=mock_df):
        cov = fetch_portfolio_covariance(["AAPL", "SBIN"])
        assert cov is not None
        assert list(cov.columns) == ["AAPL", "SBIN"]
        assert list(cov.index) == ["AAPL", "SBIN"]
        assert not cov.isna().any().any()

def test_fetch_portfolio_covariance_handles_missing_asset_gracefully():
    """Verify missing data causes fetch_portfolio_covariance to return None rather than fabricating numbers."""
    dates = pd.date_range("2026-01-01", periods=10, freq="B")
    mock_df = pd.DataFrame({
        "AAPL": [150.0 + i for i in range(10)],
        # SBIN.NS missing
    }, index=dates)

    with patch("src.api.utils.yf.download", return_value=mock_df):
        cov = fetch_portfolio_covariance(["AAPL", "SBIN"])
        assert cov is None
