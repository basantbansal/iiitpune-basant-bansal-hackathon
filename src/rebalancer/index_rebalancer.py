from typing import Dict, List, Any, Optional
import numpy as np
import pandas as pd
from .price_provider import PriceProvider
from .fx_provider import FXRateProvider, get_fx_provider
from src.engine.catalog import get_catalog


class IndexRebalancer:
    """
    Module A: Tactical High-Frequency Stock Index Rebalancer.
    Dynamically adjusts portfolio weights based on real-time NLP sentiment signals,
    enforcing tracking error bounds, simplex constraints (sum = 1.0), and generating
    auditable trade execution orders (BUY/SELL quantities) with multi-currency (USD/INR) awareness.
    """

    def __init__(
        self,
        tickers: List[str] = None,
        initial_capital: float = 1_000_000.0,
        min_weight: float = None,
        max_weight: float = None,
        alpha_tilt: float = 0.05,
        price_provider: PriceProvider = None,
        fx_provider: FXRateProvider = None,
        reporting_currency: str = "USD",
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
        self.fx_provider = fx_provider or get_fx_provider()
        self.reporting_currency = (reporting_currency or "USD").upper()
        self.catalog = get_catalog()
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

    def fetch_valuation_prices(self) -> Dict[str, float]:
        """Fetches valuation prices (cached live or reference fallback) for mark-to-market valuation."""
        if hasattr(self.price_provider, "get_valuation_prices"):
            return self.price_provider.get_valuation_prices(self.tickers)
        return self.fetch_current_prices()

    DEFAULT_SHARES_PER_CONSTITUENT: float = 10.0

    def _initialize_shares(self):
        """Initializes the baseline holdings with default 10 shares per monitored constituent, or proportional capital for custom ticker counts."""
        if len(self.tickers) == 10:
            for t in self.tickers:
                self.current_shares[t] = self.DEFAULT_SHARES_PER_CONSTITUENT
        else:
            prices = self.fetch_valuation_prices()
            per_asset_capital = self.initial_capital / len(self.tickers)
            for t in self.tickers:
                p = prices.get(t)
                if p is not None and p > 0:
                    self.current_shares[t] = per_asset_capital / p
                else:
                    self.current_shares[t] = 10.0

    def rebalance(
        self,
        signals: List[Dict[str, Any]],
        cash_balances: Optional[Dict[str, float]] = None,
        require_live: bool = False
    ) -> pd.DataFrame:
        """
        Consumes RiskSignals, calculates cross-sectional impact tilts,
        updates weights within risk constraints, and outputs multi-currency trade execution orders.
        """
        n_assets = len(self.tickers)
        base_w = 1.0 / n_assets if n_assets > 0 else 0.10

        # Fetch current market prices
        prices = self.fetch_current_prices()
        price_meta_dict = self.price_provider.get_prices_with_metadata(self.tickers)
        const_meta = price_meta_dict.get("constituents", {})

        # Fetch current FX rate for USD/INR
        fx_usd_inr = self.fx_provider.get_rate("USD", "INR")
        usd_inr_rate = fx_usd_inr.rate

        # Mark-to-market current portfolio value in reporting currency (USD)
        valid_value = 0.0
        valid_weight_sum = 0.0
        for t in self.tickers:
            p = prices.get(t) if (prices.get(t) is not None and prices.get(t) > 0) else (const_meta.get(t, {}).get("price") if const_meta.get(t) else None)
            sh = self.current_shares.get(t)
            if p is not None and sh is not None:
                inst = self.catalog.get_by_ticker(t)
                curr = inst.currency if inst else "USD"
                if curr == "USD":
                    v_reporting = sh * p
                else:
                    v_reporting = (sh * p) / usd_inr_rate
                valid_value += v_reporting
                valid_weight_sum += self.current_weights.get(t, base_w)

        if valid_weight_sum > 0:
            current_portfolio_value = valid_value / valid_weight_sum
        else:
            current_portfolio_value = self.initial_capital

        # 1. Group signals per ticker
        ticker_signals = {t: [] for t in self.tickers}
        for s in signals:
            ticker = s.get("entity", "").upper()
            if ticker in ticker_signals:
                ticker_signals[ticker].append(s)

        # 2. Compute entity-level tilts
        raw_deltas = {}
        for t in self.tickers:
            sigs = ticker_signals[t]
            if not sigs:
                raw_deltas[t] = 0.0
            else:
                weights_list = [0.5 if s.get("is_shared_headline", False) else 1.0 for s in sigs]
                w_sum = sum(weights_list) if weights_list else 1.0

                weighted_sentiment = sum(w * float(s.get("sentiment_score", 0.0)) for w, s in zip(weights_list, sigs)) / w_sum
                weighted_impact = sum(w * (float(s.get("impact_score", 5.0)) / 10.0) for w, s in zip(weights_list, sigs)) / w_sum

                is_systemic = any(
                    s.get("event_classification") in ["Credit Event", "Macroeconomic"]
                    for s in sigs
                )
                multiplier = 1.5 if (is_systemic and weighted_sentiment < 0) else 1.0

                tilt = self.alpha_tilt * weighted_sentiment * weighted_impact * multiplier
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

        w_sum = sum(target_weights.values())
        if abs(1.0 - w_sum) > 1e-5:
            raise ValueError(f"Infeasible bounds: cannot renormalize weights to 1.0 within [{self.min_weight}, {self.max_weight}]. Sum is {w_sum}")

        for t, w in target_weights.items():
            if w < self.min_weight - 1e-5 or w > self.max_weight + 1e-5:
                raise ValueError(f"Infeasible bounds: weight for {t} ({w}) violates [{self.min_weight}, {self.max_weight}]")

        final_weights = target_weights
        is_all_baseline = all(abs(final_weights[t] - base_w) < 1e-4 for t in self.tickers)

        # 5. Generate Execution Orders
        rows = []
        new_shares_held = {}

        for t in self.tickers:
            price = prices.get(t) if (prices.get(t) is not None and prices.get(t) > 0) else (const_meta.get(t, {}).get("price") if const_meta.get(t) else None)
            curr_w = self.current_weights.get(t, base_w)
            new_w = final_weights[t]
            curr_sh = self.current_shares.get(t)

            inst = self.catalog.get_by_ticker(t)
            curr = inst.currency if inst else "USD"
            curr_sym = "$" if curr == "USD" else "₹"
            market = inst.market if inst else "US"

            t_meta = const_meta.get(t, {})
            is_fallback_price = t_meta.get("is_fallback", price is None or price <= 0)
            is_fallback_fx = (curr == "INR") and (fx_usd_inr.rate <= 0 or (require_live and (fx_usd_inr.is_fallback or fx_usd_inr.is_stale)))

            fx_to_native = 1.0 if curr == "USD" else usd_inr_rate
            fx_to_usd = 1.0 if curr == "USD" else (1.0 / usd_inr_rate)
            fx_to_inr = 1.0 if curr == "INR" else usd_inr_rate
            fx_to_reporting = fx_to_inr if self.reporting_currency == "INR" else fx_to_usd

            if is_all_baseline or abs(new_w - base_w) < 1e-4:
                action = "HOLD"
                order_qty = 0.0
                signed_qty = 0.0
                trade_value_native = 0.0
                target_sh = curr_sh
                post_shares = curr_sh
                execution_status = "HOLD_NO_CHANGE"
                is_executable = True
            elif price is not None and price > 0:
                if curr_sh is not None and curr_sh > 0 and base_w > 0:
                    desired_sh = curr_sh * (new_w / base_w)
                else:
                    target_capital_usd = current_portfolio_value * new_w
                    target_capital_native = target_capital_usd * fx_to_native
                    desired_sh = target_capital_native / price
                raw_diff = desired_sh - (curr_sh if curr_sh is not None else 0.0)
                target_sh = curr_sh + raw_diff if curr_sh is not None else raw_diff

                # Check cash sufficiency for BUY orders
                trade_notional_needed = abs(raw_diff) * price
                is_cash_insufficient = False
                if raw_diff > 1e-4 and cash_balances is not None:
                    avail_cash = float(cash_balances.get(curr, 0.0))
                    if avail_cash < trade_notional_needed:
                        is_cash_insufficient = True

                is_executable = not (is_fallback_price or is_fallback_fx or is_cash_insufficient)

                if is_fallback_price:
                    execution_status = "WITHHELD_FALLBACK_PRICE"
                elif is_fallback_fx:
                    execution_status = "WITHHELD_STALE_OR_FALLBACK_FX"
                elif is_cash_insufficient:
                    execution_status = "WITHHELD_INSUFFICIENT_CASH"
                else:
                    execution_status = "EXECUTED_SIMULATED" if abs(raw_diff) >= 1e-4 else "HOLD_NO_CHANGE"

                if abs(raw_diff) < 1e-4:
                    action = "HOLD"
                    order_qty = 0.0
                    signed_qty = 0.0
                    trade_value_native = 0.0
                    post_shares = curr_sh
                    execution_status = "HOLD_NO_CHANGE"
                    is_executable = True
                elif not is_executable:
                    action = "HOLD"
                    order_qty = 0.0
                    signed_qty = 0.0
                    trade_value_native = 0.0
                    post_shares = curr_sh
                elif raw_diff > 0:
                    action = "BUY"
                    order_qty = raw_diff
                    signed_qty = order_qty
                    trade_value_native = order_qty * price
                    post_shares = (curr_sh + order_qty) if is_executable else curr_sh
                else:
                    action = "SELL"
                    order_qty = min(abs(raw_diff), curr_sh if curr_sh is not None else 0.0)
                    signed_qty = -order_qty
                    trade_value_native = order_qty * price
                    post_shares = max(0.0, curr_sh - order_qty) if is_executable else curr_sh
            else:
                target_sh = curr_sh
                post_shares = curr_sh
                order_qty = 0.0
                signed_qty = 0.0
                action = "HOLD"
                trade_value_native = 0.0
                execution_status = "WITHHELD_MISSING_PRICE"
                is_executable = False

            pre_shares_rounded = round(curr_sh, 2) if curr_sh is not None else None
            signed_qty_rounded = round(signed_qty, 2)
            post_shares_rounded = round(post_shares, 2) if post_shares is not None else None
            target_shares_rounded = round(target_sh, 2) if target_sh is not None else None

            trade_value_native_rounded = round(abs(signed_qty_rounded) * price, 2) if (price is not None and action != "HOLD") else 0.0
            trade_value_usd_rounded = round(trade_value_native_rounded * fx_to_usd, 2) if (price is not None and action != "HOLD") else 0.0
            trade_value_inr_rounded = round(trade_value_native_rounded * fx_to_inr, 2) if (price is not None and action != "HOLD") else 0.0
            trade_value_reporting = trade_value_inr_rounded if self.reporting_currency == "INR" else trade_value_usd_rounded

            est_fee_native = round(trade_value_native_rounded * 0.0010, 2)
            est_fee_usd = round(trade_value_usd_rounded * 0.0010, 2)
            est_fee_inr = round(trade_value_inr_rounded * 0.0010, 2)
            est_fee_reporting = est_fee_inr if self.reporting_currency == "INR" else est_fee_usd

            price_usd_rounded = round(price * fx_to_usd, 2) if price is not None else None
            price_inr_rounded = round(price * fx_to_inr, 2) if price is not None else None

            rows.append(
                {
                    "Ticker": t,
                    "Currency": curr,
                    "Currency Symbol": curr_sym,
                    "Reporting Currency": self.reporting_currency,
                    "Market": market,
                    "Price (Native)": round(price, 2) if price is not None else None,
                    "Price ($)": price_usd_rounded,
                    "Price (₹)": price_inr_rounded,
                    "Prev Weight": f"{curr_w * 100:.2f}%",
                    "New Weight": f"{new_w * 100:.2f}%",
                    "Delta": f"{(new_w - base_w) * 100:+.2f}%",
                    "Current Shares": pre_shares_rounded,
                    "Pre Shares": pre_shares_rounded,
                    "Target Shares": target_shares_rounded,
                    "Post Shares": post_shares_rounded,
                    "Action": action,
                    "Order Qty": round(abs(signed_qty_rounded), 2),
                    "Signed Qty": signed_qty_rounded,
                    "Trade Value (Native)": trade_value_native_rounded,
                    "Trade Value (Reporting)": trade_value_reporting,
                    "Trade Value ($)": trade_value_usd_rounded,
                    "Trade Value (₹)": trade_value_inr_rounded,
                    "Est Fee (Native)": est_fee_native,
                    "Est Fee (Reporting)": est_fee_reporting,
                    "Est Fee ($)": est_fee_usd,
                    "Est Fee (₹)": est_fee_inr,
                    "Is Executable": bool(is_executable),
                    "Execution Status": execution_status,
                }
            )

            # Current shares in engine only mutate for executed simulated trades
            new_shares_held[t] = post_shares_rounded

        # Update engine state
        self.current_weights = final_weights
        self.current_shares = new_shares_held

        df = pd.DataFrame(rows)
        return df.sort_values(by="Trade Value (Native)", ascending=False)


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
