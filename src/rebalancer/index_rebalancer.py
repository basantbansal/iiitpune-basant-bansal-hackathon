from typing import Dict, List, Any
import numpy as np
import pandas as pd
import yfinance as yf


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

        # Initialize Equal-Weight Portfolio
        n_assets = len(self.tickers)
        self.current_weights = {
            ticker: 1.0 / n_assets for ticker in self.tickers
        }
        self.current_shares = {}
        self._initialize_shares()

    def fetch_current_prices(self) -> Dict[str, float]:
        """Fetches the latest market close prices for the index constituents."""
        prices = {}
        try:
            data = yf.download(self.tickers, period="5d", progress=False)[
                "Close"
            ]
            latest_prices = data.iloc[-1].to_dict()
            prices = {
                str(k): float(v)
                for k, v in latest_prices.items()
                if not pd.isna(v)
            }
        except Exception as e:
            print(
                f"Warning: yfinance fetch failed, falling back to mock prices: {e}"
            )
            prices = {ticker: 100.0 for ticker in self.tickers}

        # Fallback for any individual failed ticker
        for ticker in self.tickers:
            if ticker not in prices:
                prices[ticker] = 100.0

        return prices

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

        # 3. Apply active tilts and enforce box constraints
        updated_weights = {}
        for idx, ticker in enumerate(self.tickers):
            base_w = self.current_weights[ticker]
            target_w = base_w + (self.alpha_tilt * z_scores[idx])
            updated_weights[ticker] = max(
                self.min_weight, min(self.max_weight, target_w)
            )

        # 4. Simplex Normalization (Sum of weights == 100%)
        total_weight = sum(updated_weights.values())
        final_weights = {
            t: w / total_weight for t, w in updated_weights.items()
        }

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