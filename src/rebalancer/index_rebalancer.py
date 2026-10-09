from typing import Dict, List, Any
import numpy as np
import pandas as pd
from .price_provider import PriceProvider


class IndexRebalancer:
    """
    Module A: Tactical High-Frequency Stock Index Rebalancer.
    Dynamically adjusts portfolio weights based on real-time NLP sentiment signals,
    enforcing tracking error bounds, simplex constraints (sum = 1.0), and generating
    auditable trade execution orders (BUY/SELL quantities).
    """

    def __init__(
        self,
        tickers: List[str] = None,
        initial_capital: float = 1_000_000.0,
        min_weight: float = 0.02,
        max_weight: float = 0.25,
        alpha_tilt: float = 0.05,
        price_provider: PriceProvider = None,
    ):
        self.tickers = tickers or [
            "AAPL",
            "MSFT",
            "NVDA",
            "AMZN",
            "GOOGL",
            "META",
            "TSLA",
            "JPM",
            "JNJ",
            "XOM",
        ]
        self.initial_capital = initial_capital
        self.min_weight = min_weight
        self.max_weight = max_weight
        self.alpha_tilt = alpha_tilt
        self.price_provider = price_provider or PriceProvider()

        # Check constraint feasibility
        n_assets = len(self.tickers)
        if self.min_weight * n_assets > 1.0:
            raise ValueError(f"Infeasible constraints: min_weight {self.min_weight} * {n_assets} assets > 1.0")
        if self.max_weight * n_assets < 1.0:
            raise ValueError(f"Infeasible constraints: max_weight {self.max_weight} * {n_assets} assets < 1.0")
        if self.min_weight > self.max_weight:
            raise ValueError("Infeasible constraints: min_weight > max_weight")

        # Initialize Equal-Weight Portfolio
        self.current_weights = {
            ticker: 1.0 / n_assets for ticker in self.tickers
        }
        self.current_shares = {}
        self._initialize_shares()

    def fetch_current_prices(self) -> Dict[str, float]:
        """Fetches the latest market close prices for the index constituents."""
        return self.price_provider.get_prices(self.tickers)

    def _initialize_shares(self):
        """Initializes the baseline holdings based on starting prices."""
        prices = self.fetch_current_prices()
        per_asset_capital = self.initial_capital / len(self.tickers)
        for t in self.tickers:
            self.current_shares[t] = per_asset_capital / prices[t]

    def rebalance(self, signals: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Consumes RiskSignals, calculates cross-sectional impact tilts,
        updates weights within risk constraints, and outputs trade execution orders.
        """
        # Fetch current market prices
        prices = self.fetch_current_prices()

        # Mark-to-market current portfolio value
        current_portfolio_value = sum(
            self.current_shares[t] * prices[t] for t in self.tickers
        )

        # 1. Aggregate signals per ticker
        ticker_tilts = {t: 0.0 for t in self.tickers}

        for s in signals:
            ticker = s.get("entity", "").upper()
            if ticker in ticker_tilts:
                # Raw tilt = Sentiment * Normalized Impact
                raw_tilt = s["sentiment_score"] * (s["impact_score"] / 10.0)

                # Penalize systemic risks heavily (Credit & Macro)
                if s["event_classification"] in [
                    "Credit Event",
                    "Macroeconomic",
                ]:
                    raw_tilt *= 1.5

                ticker_tilts[ticker] += raw_tilt

        # 2. Cross-Sectional Z-Score Standardization
        tilts_array = np.array([ticker_tilts[t] for t in self.tickers])
        std = np.std(tilts_array)

        if std > 1e-6:
            z_scores = (tilts_array - np.mean(tilts_array)) / std
        else:
            z_scores = np.zeros_like(tilts_array)

        # 3. Apply active tilts
        raw_weights = {}
        for idx, ticker in enumerate(self.tickers):
            base_w = self.current_weights[ticker]
            target_w = base_w + (self.alpha_tilt * z_scores[idx])
            raw_weights[ticker] = target_w

        # 4. Simplex Normalization and Bound Enforcement (Order-Independent Projection)
        tickers = list(self.tickers)
        x = np.array([raw_weights[t] for t in tickers])

        for _ in range(100):
            x = np.clip(x, self.min_weight, self.max_weight)
            diff = 1.0 - np.sum(x)
            if abs(diff) < 1e-8:
                break

            if diff > 0:
                unconstrained = x < self.max_weight - 1e-8
            else:
                unconstrained = x > self.min_weight + 1e-8

            if not np.any(unconstrained):
                break

            x[unconstrained] += diff / np.sum(unconstrained)

        if abs(1.0 - np.sum(x)) > 1e-6:
            raise ValueError(f"Failed to converge to valid simplex constraints. Sum is {np.sum(x)}")

        final_weights = {t: float(x[i]) for i, t in enumerate(tickers)}

        # 5. Generate Execution Orders
        rows = []
        new_shares_held = {}

        for t in self.tickers:
            price = prices[t]
            curr_w = self.current_weights[t]
            new_w = final_weights[t]

            curr_sh = self.current_shares[t]
            target_capital = current_portfolio_value * new_w
            target_sh = target_capital / price

            order_qty = target_sh - curr_sh
            action = "BUY" if order_qty > 0 else "SELL"

            rows.append(
                {
                    "Ticker": t,
                    "Price ($)": round(price, 2),
                    "Prev Weight": f"{curr_w * 100:.2f}%",
                    "New Weight": f"{new_w * 100:.2f}%",
                    "Delta": f"{(new_w - curr_w) * 100:+.2f}%",
                    "Current Shares": round(curr_sh, 2),
                    "Target Shares": round(target_sh, 2),
                    "Action": action,
                    "Order Qty": round(abs(order_qty), 2),
                    "Trade Value ($)": round(abs(order_qty) * price, 2),
                }
            )

            new_shares_held[t] = target_sh

        # Update engine state
        self.current_weights = final_weights
        self.current_shares = new_shares_held

        df = pd.DataFrame(rows)
        return df.sort_values(by="Trade Value ($)", ascending=False)


if __name__ == "__main__":
    rebalancer = IndexRebalancer()

    mock_signals = [
        {
            "entity": "NVDA",
            "sentiment_score": 0.95,
            "impact_score": 8,
            "event_classification": "Product Launch",
        },
        {
            "entity": "TSLA",
            "sentiment_score": -0.88,
            "impact_score": 9,
            "event_classification": "Credit Event",
        },
    ]

    print("\nExecuting Tactical Rebalance...\n")
    orders_df = rebalancer.rebalance(mock_signals)
    print(orders_df.to_string(index=False))
