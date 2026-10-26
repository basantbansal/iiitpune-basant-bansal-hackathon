import yfinance as yf
import numpy as np
import pandas as pd

def fetch_portfolio_covariance(tickers):
    """
    Computes annualized covariance matrix of daily percentage returns.
    Resolves symbols via InstrumentCatalog to handle provider suffixes (.NS)
    while strictly aligning output matrix rows/columns to the input ticker order.
    Returns None if data is unavailable, empty, or incomplete.
    """
    if not tickers:
        return None
    try:
        from src.engine.catalog import get_catalog
        catalog = get_catalog()
        ticker_to_provider = {}
        for t in tickers:
            inst = catalog.get_by_id(t) or catalog.get_by_ticker(t) or catalog.get_by_provider_symbol(t)
            ticker_to_provider[t] = inst.provider_symbol if inst is not None else t

        unique_provider_symbols = list(set(ticker_to_provider.values()))
        data = yf.download(unique_provider_symbols, period="1y", interval="1d", auto_adjust=True, progress=False)
        if data is None or data.empty:
            return None

        if "Close" in data.columns:
            prices = data["Close"]
        else:
            prices = data

        if isinstance(prices, pd.Series):
            prices = prices.to_frame(name=unique_provider_symbols[0])

        aligned_df = pd.DataFrame(index=prices.index)
        for t in tickers:
            prov = ticker_to_provider[t]
            if prov in prices.columns:
                aligned_df[t] = prices[prov]
            elif t in prices.columns:
                aligned_df[t] = prices[t]
            else:
                return None

        returns = aligned_df.pct_change().dropna()
        if returns.empty or len(returns) < 5:
            return None
        cov_matrix = returns[tickers].cov() * 252
        return cov_matrix
    except Exception as e:
        return None

def calculate_portfolio_volatility(weights_dict, cov_matrix, tickers):
    w = np.array([weights_dict.get(t, 0.0) for t in tickers])
    var = np.dot(w.T, np.dot(cov_matrix, w))
    return float(np.sqrt(var) * 100) # return as percentage
