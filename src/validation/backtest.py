import csv
import logging
from typing import List, Dict
from src.engine.schemas import BacktestEvent
from src.engine.risk_engine import RiskEngine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HistoricalBacktester:
    """
    Deterministic offline backtest validation engine.
    This module strictly processes historical events in chronological order,
    guaranteeing no look-ahead bias by only passing headlines to the Risk Engine.
    """

    def __init__(self, data_path: str = "data/historical_backtest.csv"):
        self.data_path = data_path
        self.risk_engine = RiskEngine()
        
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
        
        logger.info(f"Starting deterministic backtest over {total_events} events...")
        
        for event in events:
            # LOOK-AHEAD PROTECTION:
            # We strictly pass only the headline and ticker to the engine.
            # price_t1 is never exposed to the analysis phase.
            signal = self.risk_engine.analyze(text=event.headline, entity=event.ticker)
            
            # Forward return calculation
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
                "sentiment_score": signal.sentiment_score,
                "forward_return": forward_return
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
            "disclaimer": "This is a deterministic offline validation replay using synthetic data. It is NOT indicative of real-world or guaranteed investment performance."
        }
        
        logger.info(f"Backtest complete. Directional Accuracy: {directional_accuracy:.1f}%")
        return metrics

if __name__ == "__main__":
    tester = HistoricalBacktester()
    metrics = tester.run_backtest()
    print("Metrics:")
    for k, v in metrics.items():
        print(f"{k}: {v}")
