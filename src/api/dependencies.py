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

        # Restore latest target weights if available
        latest_weights = self.db.get_latest_target_weights()
        if latest_weights:
            self.rebalancer.current_weights = latest_weights

        # Load persisted historical state for display
        self.signals_log: List[Dict[str, Any]] = self.db.get_all_signals()
        
        # Restore persisted orders or reconstruct from active signals
        persisted_orders = self.db.get_latest_orders()
        if not persisted_orders.empty:
            self.latest_orders = persisted_orders
        elif self.signals_log:
            signals_for_rebalance = [
                s for s in self.signals_log
                if not s.get("is_stale", False) and (self.data_mode != "Live Market (Google RSS)" or not s.get("is_synthetic", False))
            ]
            if signals_for_rebalance:
                try:
                    self.latest_orders = self.rebalancer.rebalance(signals_for_rebalance)
                    self.db.save_latest_orders(self.latest_orders)
                except Exception:
                    self.latest_orders = pd.DataFrame()
            else:
                self.latest_orders = pd.DataFrame()
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
        elif any(v is not None for v in self.rebalancer.current_shares.values()):
            self.db.save_holdings(self.rebalancer.current_shares)
        else:
            self.rebalancer._initialize_shares()
            if any(v is not None for v in self.rebalancer.current_shares.values()):
                self.db.save_holdings(self.rebalancer.current_shares)

    async def reset_runtime(self):
        async with self.lock:
            self.db.clear_runtime_data()
            self.signals_log = []
            self.latest_orders = pd.DataFrame()
            self.last_updated = "Never"
            self.rebalancer.current_weights = {t: 1.0 / len(self.rebalancer.tickers) for t in self.rebalancer.tickers}
            self.rebalancer._initialize_shares()
            if any(v is not None for v in self.rebalancer.current_shares.values()):
                self.db.save_holdings(self.rebalancer.current_shares)

    async def get_lock(self):
        return self.lock

# Global singleton
state = None

def get_state() -> AppState:
    global state
    if state is None:
        state = AppState()
    return state
