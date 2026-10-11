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
        min_weight: float = None,
        max_weight: float = None,
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
        n_assets = len(self.tickers)
        base_w = 1.0 / n_assets

        # Default bounds: baseline +/- 5 percentage points (5%-15% for 10 assets)
        if min_weight is not None:
            self.min_weight = min_weight
        else:
            self.min_weight = max(0.0, base_w - 0.05)

        if max_weight is not None:
            self.max_weight = max_weight
        else:
            self.max_weight = min(1.0, base_w + 0.05)

        self.alpha_tilt = alpha_tilt
        self.price_provider = price_provider or PriceProvider()

        # Check constraint feasibility
        if self.min_weight * n_assets > 1.0:
            raise ValueError(f"Infeasible constraints: min_weight {self.min_weight} * {n_assets} assets > 1.0")
        if self.max_weight * n_assets < 1.0:
            raise ValueError(f"Infeasible constraints: max_weight {self.max_weight} * {n_assets} assets < 1.0")
        if self.min_weight > self.max_weight:
            raise ValueError(f"Infeasible constraints: min_weight {self.min_weight} > max_weight {self.max_weight}")

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
            p = prices.get(t)
            if p is not None and p > 0:
                self.current_shares[t] = per_asset_capital / p
            else:
                self.current_shares[t] = None

    def rebalance(self, signals: List[Dict[str, Any]]) -> pd.DataFrame:
        """
        Consumes RiskSignals, calculates cross-sectional impact tilts,
        updates weights within risk constraints, and outputs trade execution orders.
        """
        # Fetch current market prices
        prices = self.fetch_current_prices()

        # Mark-to-market current portfolio value
        valid_value = 0.0
        valid_weight_sum = 0.0
        for t in self.tickers:
            p = prices.get(t)
            sh = self.current_shares.get(t)
            if p is not None and sh is not None:
                valid_value += sh * p
                valid_weight_sum += self.current_weights[t]
                
        if valid_weight_sum > 0:
            current_portfolio_value = valid_value / valid_weight_sum
        else:
            current_portfolio_value = self.initial_capital

        n_assets = len(self.tickers)
        base_w = 1.0 / n_assets

        # 1. Group signals per ticker
        ticker_signals = {t: [] for t in self.tickers}
        for s in signals:
            ticker = s.get("entity", "").upper()
            if ticker in ticker_signals:
                ticker_signals[ticker].append(s)

        # 2. Compute entity-level tilts
        # Constituent with NO usable new signal keeps its baseline weight
        raw_deltas = {}
        for t in self.tickers:
            sigs = ticker_signals[t]
            if not sigs:
                raw_deltas[t] = 0.0
            else:
                # Signal weighting: shared multi-ticker headlines get 0.5x weight
                weights_list = [0.5 if s.get("is_shared_headline", False) else 1.0 for s in sigs]
                w_sum = sum(weights_list) if weights_list else 1.0

                weighted_sentiment = sum(w * float(s.get("sentiment_score", 0.0)) for w, s in zip(weights_list, sigs)) / w_sum
                weighted_impact = sum(w * (float(s.get("impact_score", 5.0)) / 10.0) for w, s in zip(weights_list, sigs)) / w_sum

                # Systemic risks penalize negative sentiment heavier
                is_systemic = any(
                    s.get("event_classification") in ["Credit Event", "Macroeconomic"]
                    for s in sigs
                )
                multiplier = 1.5 if (is_systemic and weighted_sentiment < 0) else 1.0

                tilt = self.alpha_tilt * weighted_sentiment * weighted_impact * multiplier
                # Bounded to baseline +/- 5% (i.e. self.min_weight - base_w, self.max_weight - base_w)
                raw_deltas[t] = float(np.clip(tilt, self.min_weight - base_w, self.max_weight - base_w))

        # 3. Balancing and Renormalization
        pos_tickers = [t for t in self.tickers if raw_deltas[t] > 0]
        neg_tickers = [t for t in self.tickers if raw_deltas[t] < 0]

        pos_sum = sum(raw_deltas[t] for t in pos_tickers)
        neg_abs_sum = sum(abs(raw_deltas[t]) for t in neg_tickers)

        target_weights = {}
        if pos_sum > 0 and neg_abs_sum > 0:
            scale = min(pos_sum, neg_abs_sum)
            for t in self.tickers:
                if t in pos_tickers:
                    d = raw_deltas[t] * (scale / pos_sum)
                elif t in neg_tickers:
                    d = raw_deltas[t] * (scale / neg_abs_sum)
                else:
                    d = 0.0
                target_weights[t] = base_w + d
        elif pos_sum == 0 and neg_abs_sum == 0:
            for t in self.tickers:
                target_weights[t] = base_w
        else:
            # Single-sided active tilts: project raw weights onto simplex with bounds
            for t in self.tickers:
                target_weights[t] = base_w + raw_deltas[t]

            x = np.array([target_weights[t] for t in self.tickers])
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

            for i, t in enumerate(self.tickers):
                target_weights[t] = float(x[i])

        # Verify sum and bounds
        w_sum = sum(target_weights.values())
        if abs(1.0 - w_sum) > 1e-5:
            raise ValueError(f"Infeasible bounds: cannot renormalize weights to 1.0 within [{self.min_weight}, {self.max_weight}]. Sum is {w_sum}")

        for t, w in target_weights.items():
            if w < self.min_weight - 1e-5 or w > self.max_weight + 1e-5:
                raise ValueError(f"Infeasible bounds: weight for {t} ({w}) violates [{self.min_weight}, {self.max_weight}]")

        final_weights = target_weights

        # Invariant: A zero-trade portfolio produces matching baseline and target weights;
        # if target weights equal baseline weights, there must not be nonzero rebalance orders.
        is_all_baseline = all(abs(final_weights[t] - base_w) < 1e-4 for t in self.tickers)

        # 5. Generate Execution Orders
        rows = []
        new_shares_held = {}

        for t in self.tickers:
            price = prices.get(t)
            curr_w = self.current_weights[t]
            new_w = final_weights[t]

            curr_sh = self.current_shares.get(t)
            
            if is_all_baseline:
                action = "HOLD"
                order_qty = 0.0
                signed_qty = 0.0
                trade_value = 0.0
                target_sh = curr_sh
            elif price is not None and price > 0:
                target_capital = current_portfolio_value * new_w
                desired_sh = target_capital / price
                if curr_sh is not None:
                    raw_diff = desired_sh - curr_sh
                else:
                    raw_diff = desired_sh

                if abs(raw_diff) < 1e-4:
                    action = "HOLD"
                    order_qty = 0.0
                    signed_qty = 0.0
                    trade_value = 0.0
                    target_sh = curr_sh
                elif raw_diff > 0:
                    action = "BUY"
                    order_qty = raw_diff
                    signed_qty = order_qty
                    trade_value = order_qty * price
                    target_sh = curr_sh + order_qty if curr_sh is not None else order_qty
                else:
                    action = "SELL"
                    order_qty = abs(raw_diff)
                    signed_qty = -order_qty
                    trade_value = order_qty * price
                    target_sh = curr_sh - order_qty if curr_sh is not None else 0.0
            else:
                target_sh = curr_sh
                order_qty = 0.0
                signed_qty = 0.0
                action = "HOLD"
                trade_value = 0.0

            pre_shares_rounded = round(curr_sh, 2) if curr_sh is not None else None
            signed_qty_rounded = round(signed_qty, 2)
            if pre_shares_rounded is not None:
                post_shares_rounded = round(pre_shares_rounded + signed_qty_rounded, 2)
            else:
                post_shares_rounded = round(target_sh, 2) if target_sh is not None else None

            trade_value_rounded = round(abs(signed_qty_rounded) * price, 2) if (price is not None and action != "HOLD") else 0.0

            rows.append(
                {
                    "Ticker": t,
                    "Price ($)": round(price, 2) if price is not None else None,
                    "Prev Weight": f"{curr_w * 100:.2f}%",
                    "New Weight": f"{new_w * 100:.2f}%",
                    "Delta": f"{(new_w - base_w) * 100:+.2f}%",
                    "Current Shares": pre_shares_rounded,
                    "Pre Shares": pre_shares_rounded,
                    "Target Shares": post_shares_rounded,
                    "Post Shares": post_shares_rounded,
                    "Action": action,
                    "Order Qty": round(abs(signed_qty_rounded), 2),
                    "Signed Qty": signed_qty_rounded,
                    "Trade Value ($)": trade_value_rounded,
                }
            )

            new_shares_held[t] = post_shares_rounded

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
