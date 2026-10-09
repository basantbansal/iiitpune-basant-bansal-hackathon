import pytest
from src.rebalancer.index_rebalancer import IndexRebalancer
import pandas as pd
import numpy as np

def test_rebalancer_order_independence():
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN"]
    signals = [
        {"entity": "NVDA", "sentiment_score": 0.9, "impact_score": 10, "event_classification": "Product Launch"},
        {"entity": "MSFT", "sentiment_score": -0.5, "impact_score": 8, "event_classification": "Macroeconomic"}
    ]

    r1 = IndexRebalancer(tickers=tickers)
    r1.rebalance(signals)
    w1 = r1.current_weights

    tickers_rev = ["AMZN", "NVDA", "MSFT", "AAPL"]
    r2 = IndexRebalancer(tickers=tickers_rev)
    r2.rebalance(signals)
    w2 = r2.current_weights

    for t in tickers:
        assert np.isclose(w1[t], w2[t], atol=1e-5)

def test_rebalancer_infeasible_constraints():
    # min_weight * assets > 1.0
    with pytest.raises(ValueError):
        IndexRebalancer(tickers=["AAPL", "MSFT", "NVDA"], min_weight=0.5, max_weight=0.9)

def test_rebalancer_bounds_enforced():
    r = IndexRebalancer(tickers=["AAPL", "MSFT", "NVDA", "AMZN"], min_weight=0.1, max_weight=0.5, alpha_tilt=0.5)
    # Huge signal for AAPL to push it to max
    signals = [{"entity": "AAPL", "sentiment_score": 1.0, "impact_score": 10, "event_classification": "Product Launch"}]
    r.rebalance(signals)

    assert np.isclose(sum(r.current_weights.values()), 1.0, atol=1e-5)
    for w in r.current_weights.values():
        assert w >= 0.1 - 1e-6
        assert w <= 0.5 + 1e-6

def test_rebalancer_extreme_inputs():
    r = IndexRebalancer(tickers=["AAPL", "MSFT"], min_weight=0.0, max_weight=1.0)
    # Max sentiment, max impact
    signals = [{"entity": "AAPL", "sentiment_score": 1000.0, "impact_score": 1000, "event_classification": "Product Launch"}]
    r.rebalance(signals)
    assert np.isclose(sum(r.current_weights.values()), 1.0, atol=1e-5)

def test_rebalancer_empty_signals():
    r = IndexRebalancer(tickers=["AAPL", "MSFT"], min_weight=0.0, max_weight=1.0)
    r.rebalance([])
    assert np.isclose(r.current_weights["AAPL"], 0.5, atol=1e-5)
    assert np.isclose(r.current_weights["MSFT"], 0.5, atol=1e-5)
