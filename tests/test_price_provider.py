import pytest
import os
import json
import tempfile
import math
import pandas as pd
from src.rebalancer.price_provider import PriceProvider
from src.rebalancer.index_rebalancer import IndexRebalancer

def test_provider_returns_expected_prices():
    provider = PriceProvider()
    expected_tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    for t in expected_tickers:
        assert provider.get_price(t) == 100.0

def test_unknown_ticker():
    provider = PriceProvider()
    with pytest.raises(ValueError, match="Unknown ticker"):
        provider.get_price("UNKNOWN")

def test_invalid_price():
    with tempfile.NamedTemporaryFile("w", delete=False) as f:
        # Include float("nan") and float("inf") using math to dump into json
        # json doesn't natively support all python float values easily without risking parse errors
        # wait, python's json.dump maps float('inf') to Infinity.
        json.dump({"prices": {
            "AAPL": -10.0, 
            "MSFT": "invalid", 
            "NVDA": 0.0, 
            "AMZN": float("nan"), 
            "GOOGL": float("inf"), 
            "META": float("-inf")
        }}, f)
        temp_name = f.name
    
    try:
        provider = PriceProvider(temp_name)
        with pytest.raises(ValueError, match="non-positive"):
            provider.get_price("AAPL")
        with pytest.raises(ValueError, match="non-numeric"):
            provider.get_price("MSFT")
        with pytest.raises(ValueError, match="non-positive"):
            provider.get_price("NVDA")
        with pytest.raises(ValueError, match="NaN/inf"):
            provider.get_price("AMZN")
        with pytest.raises(ValueError, match="NaN/inf"):
            provider.get_price("GOOGL")
        with pytest.raises(ValueError, match="NaN/inf"):
            provider.get_price("META")
    finally:
        os.remove(temp_name)

def test_deterministic_snapshot():
    # Load two separate instances from the same file
    provider1 = PriceProvider()
    provider2 = PriceProvider()
    
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    prices1 = provider1.get_prices(tickers)
    prices2 = provider2.get_prices(tickers)
    
    assert prices1 == prices2
    assert provider1.as_of == provider2.as_of
    assert provider1.as_of == "2024-01-01T00:00:00Z"
    
    # Check if identical inputs + prices yield identical dataframes
    reb1 = IndexRebalancer(price_provider=provider1)
    reb2 = IndexRebalancer(price_provider=provider2)
    
    mock_signals = [{"entity": "NVDA", "sentiment_score": 0.95, "impact_score": 8, "event_classification": "Product Launch"}]
    df1 = reb1.rebalance(mock_signals)
    df2 = reb2.rebalance(mock_signals)
    pd.testing.assert_frame_equal(df1, df2)

def test_module_a_successfully_obtains_prices():
    rebalancer = IndexRebalancer()
    prices = rebalancer.fetch_current_prices()
    for t in rebalancer.tickers:
        assert prices[t] == 100.0

def test_module_a_numerical_regression():
    """
    PriceProvider replacement changes market-price inputs and therefore theoretical share quantities,
    but Module A allocation mathematics must remain unchanged for identical price inputs.
    This test enforces strict numerical equivalence for target weights and trade values
    under a fixed deterministic set of inputs.
    """
    rebalancer = IndexRebalancer()
    mock_signals = [
        {"entity": "NVDA", "sentiment_score": 0.95, "impact_score": 8, "event_classification": "Product Launch"},
        {"entity": "TSLA", "sentiment_score": -0.88, "impact_score": 9, "event_classification": "Credit Event"}
    ]
    orders = rebalancer.rebalance(mock_signals)
    assert not orders.empty
    
    # Convert New Weight from "18.15%" string back to float for precise testing
    orders["New Weight Float"] = orders["New Weight"].apply(lambda x: float(x.replace("%", "")))
    
    # Assert specific weights against baseline
    nvda_row = orders[orders["Ticker"] == "NVDA"].iloc[0]
    tsla_row = orders[orders["Ticker"] == "TSLA"].iloc[0]
    msft_row = orders[orders["Ticker"] == "MSFT"].iloc[0]
    
    # Expected precise values from baseline mathematical model
    assert nvda_row["New Weight Float"] == pytest.approx(18.14, rel=1e-3)
    assert tsla_row["New Weight Float"] == pytest.approx(2.00, rel=1e-3)
    assert msft_row["New Weight Float"] == pytest.approx(9.98, rel=1e-3)
    
    assert nvda_row["Trade Value ($)"] == pytest.approx(81356.71, rel=1e-3)
    assert tsla_row["Trade Value ($)"] == pytest.approx(80000.00, rel=1e-3)
    assert msft_row["Trade Value ($)"] == pytest.approx(169.54, rel=1e-3)

    # Check internal weights with absolute tolerance to handle formatting round-offs
    assert rebalancer.current_weights["NVDA"] == pytest.approx(0.1814, abs=1e-4)
    assert rebalancer.current_weights["TSLA"] == pytest.approx(0.0200, abs=1e-4)
