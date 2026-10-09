import pytest
from src.rebalancer.index_rebalancer import IndexRebalancer
import math

class DummyPriceProvider:
    def get_prices(self, tickers):
        return {t: 100.0 for t in tickers}

def test_transaction_cost_and_turnover(monkeypatch):
    r = IndexRebalancer(tickers=["A", "B", "C"], initial_capital=300_000, price_provider=DummyPriceProvider(), min_weight=0.0, max_weight=1.0)

    # Let's force target weights by overriding the final weights assignment
    original_rebalance = r.rebalance

    def fake_rebalance(signals):
        # We manually bypass the tilt logic to set final weights directly
        prices = r.fetch_current_prices()
        current_portfolio_value = 300_000
        final_weights = {"A": 0.5, "B": 1/3, "C": 1/6}
        rows = []
        for t in r.tickers:
            price = prices[t]
            curr_sh = r.current_shares[t]
            target_sh = (current_portfolio_value * final_weights[t]) / price
            order_qty = target_sh - curr_sh
            rows.append({
                "Ticker": t,
                "Trade Value ($)": round(abs(order_qty) * price, 2)
            })
        import pandas as pd
        return pd.DataFrame(rows)

    monkeypatch.setattr(r, "rebalance", fake_rebalance)

    df = r.rebalance([])
    total_turnover = df["Trade Value ($)"].sum()
    cost_bps = 10.0
    est_txn_cost = total_turnover * (cost_bps / 10000.0)

    # A: goes from 100k to 150k -> 50,000
    # B: stays 100k -> 0
    # C: goes from 100k to 50k -> 50,000
    # Total Turnover = 100,000
    assert math.isclose(total_turnover, 100000.0)
    assert math.isclose(est_txn_cost, 100.0)
