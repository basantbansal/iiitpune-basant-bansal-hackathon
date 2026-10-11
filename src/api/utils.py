import yfinance as yf
import numpy as np
import pandas as pd

def fetch_portfolio_covariance(tickers):
    try:
        data = yf.download(tickers, period="1y", interval="1d", auto_adjust=True, progress=False)
        if "Close" in data.columns:
            prices = data["Close"]
        else:
            prices = data
        returns = prices.pct_change().dropna()
        # Ensure the columns match the order of tickers provided
        returns = returns[tickers]
        cov_matrix = returns.cov() * 252
        return cov_matrix
    except Exception as e:
        return None

def calculate_portfolio_volatility(weights_dict, cov_matrix, tickers):
    w = np.array([weights_dict.get(t, 0.0) for t in tickers])
    var = np.dot(w.T, np.dot(cov_matrix, w))
    return float(np.sqrt(var) * 100) # return as percentage
