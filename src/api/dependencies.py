import asyncio
from typing import List, Dict, Any
import pandas as pd
from datetime import datetime

from src.engine.risk_engine import RiskEngine
from src.rebalancer.index_rebalancer import IndexRebalancer
from src.engine.ingestion import MarketNewsIngestion
from src.storage.db import SignalDatabase
from src.stress_testing.stress_engine import StressEngine

class AppState:
    def __init__(self, db: SignalDatabase = None):
        self.db = db or SignalDatabase()
        
        # Load persisted config or use defaults
        config_record = self.db.get_config()
        if not config_record:
            config_record = {
                "initial_capital": 1000000.0,
                "alpha_tilt": 0.05,
                "data_mode": "Live Market (Google RSS)",
                "max_items": 2
            }
            self.db.save_config(config_record)
            
        self.initial_capital = config_record["initial_capital"]
        self.alpha_tilt = config_record["alpha_tilt"]
        self.data_mode = config_record["data_mode"]
        self.max_items = config_record.get("max_items", 2)

        self.risk_engine = RiskEngine()
        self.rebalancer = IndexRebalancer(
            initial_capital=self.initial_capital,
            alpha_tilt=self.alpha_tilt
        )
        self.ingestor = MarketNewsIngestion()
        self.stress_engine = StressEngine()
        
        # Restore persisted holdings if they exist
        persisted_shares = self.db.get_holdings()
        if persisted_shares:
            self.rebalancer.current_shares = persisted_shares
        elif any(v is not None for v in self.rebalancer.current_shares.values()):
            self.db.save_holdings(self.rebalancer.current_shares)

        # Restore persisted cash balance if available, or initialize from budget minus invested holdings
        persisted_cash = self.db.get_cash()
        if persisted_cash is not None:
            self.cash_balance = float(persisted_cash)
        else:
            prices = self.rebalancer.fetch_current_prices()
            invested_val = sum(float(self.rebalancer.current_shares.get(t, 10.0) or 0.0) * (prices.get(t) or 100.0) for t in self.rebalancer.tickers)
            self.cash_balance = max(0.0, round(float(self.initial_capital) - invested_val, 2))
            self.db.save_cash(self.cash_balance)

        # Restore latest target weights if available
        latest_weights = self.db.get_latest_target_weights()
        if latest_weights:
            self.rebalancer.current_weights = latest_weights

        # Load persisted historical state for display
        self.signals_log: List[Dict[str, Any]] = self.db.get_all_signals()
        
        # Restore persisted orders
        persisted_orders = self.db.get_latest_orders()
        if not persisted_orders.empty:
            self.latest_orders = persisted_orders
        else:
            self.latest_orders = pd.DataFrame()

        self.last_updated: str = "Never"
        if self.signals_log:
            last_sig = self.signals_log[-1]
            self.last_updated = last_sig.get("published_at", "Restored")

        self.auto_trigger_stress: Any = None
        self.lock = asyncio.Lock()

    def sync_holdings(self):
        persisted = self.db.get_holdings()
        if persisted:
            self.rebalancer.current_shares = persisted
        else:
            self.rebalancer._initialize_shares()
            self.db.save_holdings(self.rebalancer.current_shares)

        persisted_cash = self.db.get_cash()
        if persisted_cash is not None:
            self.cash_balance = float(persisted_cash)
        else:
            prices = self.rebalancer.fetch_current_prices()
            invested_val = sum(float(self.rebalancer.current_shares.get(t, 10.0) or 0.0) * (prices.get(t) or 100.0) for t in self.rebalancer.tickers)
            self.cash_balance = max(0.0, round(float(self.initial_capital) - invested_val, 2))
            self.db.save_cash(self.cash_balance)

    async def reset_runtime(self):
        async with self.lock:
            self.db.clear_runtime_data()
            self.signals_log = []
            self.latest_orders = pd.DataFrame()
            self.last_updated = "Never"
            self.rebalancer.current_weights = {t: 1.0 / len(self.rebalancer.tickers) for t in self.rebalancer.tickers}
            self.rebalancer._initialize_shares()
            self.db.save_holdings(self.rebalancer.current_shares)
            prices = self.rebalancer.fetch_current_prices()
            invested_val = sum(float(self.rebalancer.current_shares.get(t, 10.0) or 0.0) * (prices.get(t) or 100.0) for t in self.rebalancer.tickers)
            remaining_cash = max(0.0, round(float(self.initial_capital) - invested_val, 2))
            self.cash_balance = remaining_cash
            self.db.save_cash(remaining_cash)

    async def get_lock(self):
        return self.lock

# Global singleton
state = None

def get_state() -> AppState:
    global state
    if state is None:
        state = AppState()
    return state
