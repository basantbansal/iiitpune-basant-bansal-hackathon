import pytest
import os
import pandas as pd
from unittest.mock import patch
from src.rebalancer.price_provider import PriceProvider
from src.rebalancer.index_rebalancer import IndexRebalancer

@pytest.fixture
def mock_yfinance():
    with patch("src.rebalancer.price_provider.yf.download") as mock_download:
        yield mock_download

def make_mock_df(prices_dict):
    df = pd.DataFrame([prices_dict])
    df.index = pd.to_datetime(["2024-01-01"])
    # yf.download returns a DataFrame where columns are tickers if 'Close' is not in columns, 
    # but normally it returns a MultiIndex or columns with 'Close'.
    # PriceProvider does: `if "Close" in data.columns: close_prices = data["Close"].iloc[-1]`
    # Let's just return a DataFrame with "Close" in columns? No, if we just return a flat DF,
    # PriceProvider falls back to `data.iloc[-1]`.
    return df

def test_provider_returns_expected_prices(mock_yfinance):
    expected_tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    mock_yfinance.return_value = make_mock_df({t: 100.0 for t in expected_tickers})
    
    provider = PriceProvider()
    provider.refresh_prices(expected_tickers)
    for t in expected_tickers:
        assert provider.get_price(t) == 100.0

def test_unknown_ticker(mock_yfinance):
    # The requirement is that get_price returns None for unknown, 
    # but the old test expected ValueError("Unknown ticker").
    # Wait, PriceProvider in production returns None or just doesn't fail.
    # The prompt says: "Test successful retrieval, unknown tickers, invalid/nonpositive prices, empty responses, exceptions, and unavailable data."
    mock_yfinance.return_value = make_mock_df({"AAPL": 100.0})
    provider = PriceProvider()
    provider.refresh_prices(["UNKNOWN"])
    assert provider.get_price("UNKNOWN") is None

def test_invalid_price(mock_yfinance):
    mock_yfinance.return_value = make_mock_df({
        "AAPL": -10.0, 
        "MSFT": "invalid", 
        "NVDA": 0.0, 
        "AMZN": float("nan"), 
        "GOOGL": float("inf"), 
        "META": float("-inf")
    })
    
    provider = PriceProvider()
    provider.refresh_prices(["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META"])
    
    assert provider.get_price("AAPL") is None
    assert provider.get_price("MSFT") is None
    assert provider.get_price("NVDA") is None
    assert provider.get_price("AMZN") is None
    assert provider.get_price("GOOGL") is None
    assert provider.get_price("META") is None

def test_empty_response(mock_yfinance):
    mock_yfinance.return_value = pd.DataFrame()
    provider = PriceProvider()
    provider.refresh_prices(["AAPL"])
    assert provider.get_price("AAPL") is None

def test_exception_during_fetch(mock_yfinance):
    mock_yfinance.side_effect = Exception("Network error")
    provider = PriceProvider()
    provider.refresh_prices(["AAPL"])
    assert provider.get_price("AAPL") is None

def test_deterministic_snapshot(mock_yfinance):
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    mock_yfinance.return_value = make_mock_df({t: 100.0 for t in tickers})
    
    provider1 = PriceProvider()
    provider2 = PriceProvider()
    
    provider1.refresh_prices(tickers)
    provider2.refresh_prices(tickers)
    
    prices1 = provider1.get_prices(tickers)
    prices2 = provider2.get_prices(tickers)
    
    assert prices1 == prices2
    
    reb1 = IndexRebalancer(price_provider=provider1)
    reb2 = IndexRebalancer(price_provider=provider2)
    
    # Must explicitly initialize shares with refreshed prices
    reb1._initialize_shares()
    reb2._initialize_shares()
    
    mock_signals = [{"entity": "NVDA", "sentiment_score": 0.95, "impact_score": 8, "event_classification": "Product Launch"}]
    df1 = reb1.rebalance(mock_signals)
    df2 = reb2.rebalance(mock_signals)
    pd.testing.assert_frame_equal(df1, df2)

def test_module_a_successfully_obtains_prices(mock_yfinance):
    mock_yfinance.return_value = make_mock_df({t: 100.0 for t in ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]})
    rebalancer = IndexRebalancer()
    rebalancer.price_provider.refresh_prices(rebalancer.tickers)
    prices = rebalancer.fetch_current_prices()
    for t in rebalancer.tickers:
        assert prices[t] == 100.0

def test_module_a_numerical_regression(mock_yfinance):
    mock_yfinance.return_value = make_mock_df({t: 100.0 for t in ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]})
    rebalancer = IndexRebalancer()
    rebalancer.price_provider.refresh_prices(rebalancer.tickers)
    rebalancer._initialize_shares() # Re-init shares now that prices are 100.0
    
    mock_signals = [
        {"entity": "NVDA", "sentiment_score": 0.95, "impact_score": 8, "event_classification": "Product Launch"},
        {"entity": "TSLA", "sentiment_score": -0.88, "impact_score": 9, "event_classification": "Credit Event"}
    ]
    orders = rebalancer.rebalance(mock_signals)
    assert not orders.empty
    
    orders["New Weight Float"] = orders["New Weight"].apply(lambda x: float(x.replace("%", "")))
    
    nvda_row = orders[orders["Ticker"] == "NVDA"].iloc[0]
    tsla_row = orders[orders["Ticker"] == "TSLA"].iloc[0]
    msft_row = orders[orders["Ticker"] == "MSFT"].iloc[0]
    
    assert nvda_row["New Weight Float"] == pytest.approx(13.80, rel=1e-3)
    assert tsla_row["New Weight Float"] == pytest.approx(6.20, rel=1e-3)
    assert msft_row["New Weight Float"] == pytest.approx(10.00, rel=1e-3)
    
    assert nvda_row["Trade Value ($)"] == pytest.approx(38000.00, rel=1e-3)
    assert tsla_row["Trade Value ($)"] == pytest.approx(38000.00, rel=1e-3)
    assert msft_row["Trade Value ($)"] == pytest.approx(0.00, abs=1e-2)

    assert rebalancer.current_weights["NVDA"] == pytest.approx(0.1380, abs=1e-4)
    assert rebalancer.current_weights["TSLA"] == pytest.approx(0.0620, abs=1e-4)
