import pytest
import pandas as pd
import numpy as np
from unittest.mock import patch, MagicMock
from src.dashboard.stock_detail import fetch_stock_data, compute_rsi, compute_macd

def test_compute_rsi():
    prices = pd.Series([100, 102, 104, 103, 105, 107, 106, 108, 110, 109, 111, 113, 112, 114, 116])
    rsi = compute_rsi(prices, window=14)
    assert not rsi.isna().all()
    assert rsi.iloc[-1] > 0 and rsi.iloc[-1] < 100

def test_compute_macd():
    prices = pd.Series(np.linspace(100, 200, 50))
    macd, sig = compute_macd(prices)
    assert not macd.isna().all()
    assert not sig.isna().all()

@patch('yfinance.Ticker')
def test_fetch_stock_data_success(mock_ticker):
    mock_hist = pd.DataFrame({
        'Open': [100, 101], 'High': [102, 103], 'Low': [99, 100], 'Close': [101, 102], 'Volume': [1000, 1100]
    }, index=pd.to_datetime(['2023-01-01', '2023-01-02']))
    mock_instance = mock_ticker.return_value
    mock_instance.history.return_value = mock_hist
    
    df = fetch_stock_data("AAPL", "1M")
    assert df is not None
    assert len(df) == 2
    assert 'Close' in df.columns

@patch('yfinance.Ticker')
def test_fetch_stock_data_empty(mock_ticker):
    mock_instance = mock_ticker.return_value
    mock_instance.history.return_value = pd.DataFrame()
    
    df = fetch_stock_data("UNKNOWN", "1M")
    assert df is None

@patch('yfinance.Ticker')
def test_fetch_stock_data_failure(mock_ticker):
    fetch_stock_data.clear()
    fetch_stock_data.clear()
    fetch_stock_data.clear()
    mock_instance = mock_ticker.return_value
    mock_instance.history.side_effect = Exception("API Error")
    
    df = fetch_stock_data("AAPL", "1M")
    assert df is None

def test_ticker_selection():
    # Simulate ticker selection logic
    session_state = {"latest_orders": pd.DataFrame([{"Ticker": "AAPL"}, {"Ticker": "MSFT"}]), "selected_stock": None}
    
    # Event comes from streamlit
    event = {"selection": {"rows": [1]}}
    if event and "selection" in event and event["selection"]["rows"]:
        row_idx = event["selection"]["rows"][0]
        ticker = session_state["latest_orders"].iloc[row_idx]["Ticker"]
        session_state["selected_stock"] = ticker
        
    assert session_state["selected_stock"] == "MSFT"
    
    # Switch ticker
    event = {"selection": {"rows": [0]}}
    if event and "selection" in event and event["selection"]["rows"]:
        row_idx = event["selection"]["rows"][0]
        ticker = session_state["latest_orders"].iloc[row_idx]["Ticker"]
        session_state["selected_stock"] = ticker
        
    assert session_state["selected_stock"] == "AAPL"
