import csv
import logging
from typing import List, Dict
from src.engine.schemas import BacktestEvent
from src.engine.risk_engine import RiskEngine
from src.rebalancer.index_rebalancer import IndexRebalancer
from src.rebalancer.price_provider import PriceProvider

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MockPriceProvider(PriceProvider):
    """Minimal local deterministic price provider used ONLY by the replay engine."""
    def __init__(self, t0_prices: Dict[str, float]):
        super().__init__()
        self._prices = t0_prices
        self._as_of = "T0_REPLAY"

    def _load_data(self):
        pass  # Do not load from file, we inject prices directly

class HistoricalBacktester:
    """
    Deterministic offline backtest validation engine.
    This module strictly processes historical events in chronological order,
    guaranteeing no look-ahead bias by only passing headlines to the Risk Engine.
    """

    def __init__(self, data_path: str = "data/historical_backtest.csv"):
        self.data_path = data_path
        self.risk_engine = RiskEngine()
        # Base reference prices for non-event tickers
        base_pp = PriceProvider()
        self.reference_prices = base_pp.get_prices(
            ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
        )

    def load_events(self) -> List[BacktestEvent]:
        events = []
        try:
            with open(self.data_path, "r", encoding="utf-8") as f:
                lines = [line for line in f if not line.startswith("#")]
                reader = csv.DictReader(lines)
                for row in reader:
                    event = BacktestEvent(
                        event_id=row["event_id"],
                        event_timestamp=row["event_timestamp"],
                        ticker=row["ticker"],
                        headline=row["headline"],
                        price_t0=float(row["price_t0"]),
                        price_t1=float(row["price_t1"])
                    )
                    events.append(event)
        except Exception as e:
            logger.error(f"Failed to load backtest data: {e}")
            raise

        # Sort chronologically to ensure no look-ahead bias in processing
        events.sort(key=lambda x: x.event_timestamp)
        return events

    def run_backtest(self) -> Dict:
        """
        Executes the backtest over the chronological events.
        """
        events = self.load_events()
        results = []

        total_events = len(events)
        correct_direction = 0
        sum_forward_return = 0.0
        conditional_returns = {"positive_signal": [], "negative_signal": []}

        # New P&L metrics
        total_incremental_pnl = 0.0

        logger.info(f"Starting deterministic backtest over {total_events} events...")

        for event in events:
            # 1. Generate RiskSignal
            signal = self.risk_engine.analyze(text=event.headline, entity=event.ticker)

            # 2. Build T0 price provider
            t0_prices = self.reference_prices.copy()
            t0_prices[event.ticker] = event.price_t0
            mock_pp = MockPriceProvider(t0_prices)

            # 3. Instantiate fresh IndexRebalancer
            rebalancer = IndexRebalancer(price_provider=mock_pp)

            # Baseline portfolio setup (equal weight at T0)
            baseline_shares = {t: (rebalancer.initial_capital / len(rebalancer.tickers)) / t0_prices[t] for t in rebalancer.tickers}
            baseline_value_t0 = rebalancer.initial_capital

            # 4. Execute existing Module A rebalance
            # Pass signal to rebalancer
            _ = rebalancer.rebalance([signal.to_dict()])

            # 5. Capture the resulting portfolio/share state
            rebalanced_shares = rebalancer.current_shares
            rebalanced_value_t0 = rebalancer.initial_capital

            # 6. ONLY NOW use price_t1 for mark-to-market
            t1_prices = t0_prices.copy()
            t1_prices[event.ticker] = event.price_t1

            # 7. Calculate baseline and rebalanced portfolio values/P&L
            baseline_value_t1 = sum(baseline_shares[t] * t1_prices[t] for t in rebalancer.tickers)
            rebalanced_value_t1 = sum(rebalanced_shares[t] * t1_prices[t] for t in rebalancer.tickers)

            baseline_pnl = baseline_value_t1 - baseline_value_t0
            rebalanced_pnl = rebalanced_value_t1 - rebalanced_value_t0
            incremental_pnl = rebalanced_pnl - baseline_pnl

            baseline_return_pct = (baseline_pnl / baseline_value_t0) * 100
            rebalanced_return_pct = (rebalanced_pnl / rebalanced_value_t0) * 100

            total_incremental_pnl += incremental_pnl

            # Signal directional metrics
            forward_return = (event.price_t1 - event.price_t0) / event.price_t0
            sum_forward_return += forward_return

            signal_direction = 1 if signal.sentiment_score > 0 else (-1 if signal.sentiment_score < 0 else 0)
            return_direction = 1 if forward_return > 0 else (-1 if forward_return < 0 else 0)

            if signal_direction == return_direction and signal_direction != 0:
                correct_direction += 1

            if signal.sentiment_score > 0:
                conditional_returns["positive_signal"].append(forward_return)
            elif signal.sentiment_score < 0:
                conditional_returns["negative_signal"].append(forward_return)

            results.append({
                "event_id": event.event_id,
                "ticker": event.ticker,
                "forward_return": forward_return,
                "signal_direction": signal_direction,
                "baseline_pnl": baseline_pnl,
                "rebalanced_pnl": rebalanced_pnl,
                "incremental_pnl": incremental_pnl,
                "baseline_return_pct": baseline_return_pct,
                "rebalanced_return_pct": rebalanced_return_pct
            })

        directional_accuracy = (correct_direction / total_events * 100) if total_events > 0 else 0.0
        avg_return = (sum_forward_return / total_events * 100) if total_events > 0 else 0.0

        avg_pos_return = (sum(conditional_returns["positive_signal"]) / len(conditional_returns["positive_signal"]) * 100) if conditional_returns["positive_signal"] else 0.0
        avg_neg_return = (sum(conditional_returns["negative_signal"]) / len(conditional_returns["negative_signal"]) * 100) if conditional_returns["negative_signal"] else 0.0

        metrics = {
            "total_events": total_events,
            "directional_accuracy_pct": directional_accuracy,
            "average_forward_return_pct": avg_return,
            "avg_conditional_return_positive_signal_pct": avg_pos_return,
            "avg_conditional_return_negative_signal_pct": avg_neg_return,
            "total_incremental_pnl": total_incremental_pnl,
            "events_results": results,
            "disclaimer": "This is a deterministic offline replay using synthetic validation data. It demonstrates pipeline mechanics only and is NOT evidence of real-world investment performance, guaranteed returns, or alpha.",
            "costs_note": "Results are gross of transaction costs, slippage, and execution latency."
        }

        logger.info(f"Backtest complete. Directional Accuracy: {directional_accuracy:.1f}%. Total Incremental P&L: ${total_incremental_pnl:,.2f}")
        return metrics

if __name__ == "__main__":
    tester = HistoricalBacktester()
    metrics = tester.run_backtest()
    print("Metrics:")
    for k, v in metrics.items():
        if k == "events_results":
            continue
        print(f"{k}: {v}")

    print("\nEvent Details:")
    for r in metrics["events_results"]:
        print(r)
