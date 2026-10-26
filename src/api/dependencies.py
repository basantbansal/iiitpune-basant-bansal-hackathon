import asyncio
from typing import List, Dict, Any
import pandas as pd
from datetime import datetime

from src.engine.risk_engine import RiskEngine
from src.rebalancer.index_rebalancer import IndexRebalancer
from src.engine.ingestion import MarketNewsIngestion
from src.storage.db import SignalDatabase
from src.stress_testing.stress_engine import StressEngine
from src.engine.catalog import get_catalog
from src.rebalancer.fx_provider import FXRateProvider, get_fx_provider

class AppState:
    def __init__(self, db: SignalDatabase = None):
        self.db = db or SignalDatabase()
        self.catalog = get_catalog()
        self.fx_provider = get_fx_provider()
        
        # Load persisted config or use defaults (INR default reporting currency)
        config_record = self.db.get_config()
        if not config_record:
            config_record = {
                "initial_capital": 1000000.0,
                "alpha_tilt": 0.05,
                "data_mode": "Live Market (Google RSS)",
                "max_items": 2,
                "reporting_currency": None
            }
            self.db.save_config(config_record)
            
        self.initial_capital = config_record["initial_capital"]
        self.alpha_tilt = config_record["alpha_tilt"]
        self.data_mode = config_record["data_mode"]
        self.max_items = config_record.get("max_items", 2)
        # Restore persisted universe selection or default to 10 original US stocks
        persisted_selection = self.db.get_universe_selection()
        if persisted_selection:
            try:
                validated_insts = self.catalog.validate_selection(persisted_selection)
                self.selected_ids = [inst.id for inst in validated_insts]
            except Exception:
                self.selected_ids = list(self.catalog.get_default_selection_ids())
                self.db.save_universe_selection(self.selected_ids)
        else:
            self.selected_ids = list(self.catalog.get_default_selection_ids())
            self.db.save_universe_selection(self.selected_ids)

        active_tickers = [self.catalog.get_by_id(i_id).display_ticker for i_id in self.selected_ids]

        # Determine reporting currency
        self.reporting_currency = config_record.get("reporting_currency") or "USD"

        self.risk_engine = RiskEngine()
        self.rebalancer = IndexRebalancer(
            tickers=active_tickers,
            initial_capital=self.get_initial_capital_in_reporting_currency(self.reporting_currency),
            alpha_tilt=self.alpha_tilt,
            fx_provider=self.fx_provider,
            reporting_currency=self.reporting_currency
        )
        self.ingestor = MarketNewsIngestion()
        self.stress_engine = StressEngine()
        
        # Restore persisted holdings if they exist, filtering strictly to active constituents
        persisted_shares = self.db.get_holdings()
        if persisted_shares:
            self.rebalancer.current_shares = {
                t: persisted_shares.get(t, self.rebalancer.DEFAULT_SHARES_PER_CONSTITUENT)
                for t in active_tickers
            }
        elif any(v is not None for v in self.rebalancer.current_shares.values()):
            self.db.save_holdings(self.rebalancer.current_shares)

        # Restore persisted cash balances (USD and INR separate)
        persisted_cash_balances = self.db.get_cash_balances()
        if persisted_cash_balances and any(v > 0 for v in persisted_cash_balances.values()):
            self.cash_balances = dict(persisted_cash_balances)
        else:
            self.cash_balances = self._calculate_initial_cash(active_tickers, self.rebalancer.current_shares)
            self.db.save_cash_balances(self.cash_balances)

        # Restore latest target weights if available and matching active constituents
        latest_weights = self.db.get_latest_target_weights()
        if latest_weights and all(t in latest_weights for t in active_tickers):
            self.rebalancer.current_weights = latest_weights
        else:
            self.rebalancer.current_weights = {t: 1.0 / len(active_tickers) for t in active_tickers}

        # Load persisted historical state for display
        self.signals_log: List[Dict[str, Any]] = self.db.get_all_signals()
        
        # Restore persisted orders
        persisted_orders = self.db.get_latest_orders()
        if not persisted_orders.empty:
            self.latest_orders = persisted_orders
        else:
            self.latest_orders = pd.DataFrame()

        self.last_updated: str = "No scan executed yet"
        if self.signals_log:
            last_sig = self.signals_log[-1]
            self.last_updated = last_sig.get("published_at", "No scan executed yet")

        # Restore cumulative fees
        self.cumulative_fees: Dict[str, float] = self.db.get_cumulative_fees()

        self.latest_scan_coverage = {
            t: {
                "ticker": t,
                "company_name": self.ingestor.get_company_name(t),
                "raw_retrieved": 0,
                "fresh_retained": 0,
                "rejected_stale": 0,
                "rejected_irrelevant": 0,
                "assigned_to_company": 0,
                "analyzed_count": 0,
                "signals_count": 0,
                "feed_status": "READY",
                "coverage_state": "NO_SCAN_EXECUTED_YET"
            }
            for t in active_tickers
        }

        self.auto_trigger_stress: Any = None
        self.lock = asyncio.Lock()

    def apply_executed_orders(self, orders_df: pd.DataFrame):
        """
        Accounting integrity:
        Debits/credits native cash balances and records cumulative fees ONLY for executed simulated orders.
        Withheld orders or HOLDs do not mutate cash or incur fees.
        Fees are accounted for exactly once.
        """
        if orders_df is None or orders_df.empty:
            return

        for _, row in orders_df.iterrows():
            if not bool(row.get("Is Executable", False)):
                continue
            if str(row.get("Execution Status", "")) != "EXECUTED_SIMULATED":
                continue
            action = str(row.get("Action", "HOLD"))
            if action not in ("BUY", "SELL"):
                continue

            curr = str(row.get("Currency", "USD"))
            trade_val = float(row.get("Trade Value (Native)", 0.0) or 0.0)
            fee = float(row.get("Est Fee (Native)", 0.0) or 0.0)

            if action == "BUY":
                self.cash_balances[curr] = max(0.0, round(self.cash_balances.get(curr, 0.0) - trade_val - fee, 2))
            elif action == "SELL":
                self.cash_balances[curr] = max(0.0, round(self.cash_balances.get(curr, 0.0) + trade_val - fee, 2))

            self.cumulative_fees[curr] = round(self.cumulative_fees.get(curr, 0.0) + fee, 2)

        self.db.save_cash_balances(self.cash_balances)
        self.db.save_cumulative_fees(self.cumulative_fees)

    def get_initial_capital_in_reporting_currency(self, target_currency: str = None) -> float:
        """
        Conversion and migration policy:
        If stored initial_capital is a legacy USD budget (<= 2,000,000):
          - In INR: converts to INR using verified FX rate (e.g. $1,000,000 * 84 = ₹84,000,000)
          - In USD: retains native USD amount
        If stored initial_capital was set in INR (>= 10,000,000):
          - In INR: retains native INR amount
          - In USD: converts to USD equivalent
        """
        curr = (target_currency or self.reporting_currency or "INR").upper()
        fx_rate = self.fx_provider.get_rate("USD", "INR").rate
        cap = float(self.initial_capital)

        if curr == "INR":
            if cap <= 2_000_000.0:
                return round(cap * fx_rate, 2)
            return cap
        else:
            if cap >= 10_000_000.0:
                return round(cap / fx_rate, 2)
            return cap

    def _calculate_initial_cash(self, tickers: List[str], shares_map: Dict[str, float]) -> Dict[str, float]:
        """Calculates initial cash balances so that Cash + Holdings Market Value == Initial Capital."""
        val_prices = self.rebalancer.price_provider.get_valuation_prices(tickers)
        usd_tickers = [t for t in tickers if (self.catalog.get_by_ticker(t) and self.catalog.get_by_ticker(t).currency == "USD") or not self.catalog.get_by_ticker(t)]
        inr_tickers = [t for t in tickers if (self.catalog.get_by_ticker(t) and self.catalog.get_by_ticker(t).currency == "INR")]

        usd_invested = sum(
            float(shares_map.get(t, 10.0) or 0.0) * float(val_prices.get(t, 100.0))
            for t in usd_tickers
        )
        inr_invested = sum(
            float(shares_map.get(t, 10.0) or 0.0) * float(val_prices.get(t, 1000.0))
            for t in inr_tickers
        )

        usd_inr_rate = self.fx_provider.get_rate("USD", "INR").rate
        total_inr_budget = self.get_initial_capital_in_reporting_currency("INR")
        total_usd_budget = self.get_initial_capital_in_reporting_currency("USD")

        if len(inr_tickers) > 0 and len(usd_tickers) == 0:
            if self.reporting_currency == "INR":
                avail_inr = max(0.0, round(total_inr_budget - inr_invested, 2))
                return {"USD": 0.0, "INR": avail_inr}
            else:
                # In USD reporting mode with India-only portfolio, USD cash remains full capital reserves ($1,000,000)
                return {"USD": float(total_usd_budget), "INR": 0.0}
        elif len(usd_tickers) > 0 and len(inr_tickers) == 0:
            avail_usd = max(0.0, round(total_usd_budget - usd_invested, 2))
            return {"USD": 0.0 if self.reporting_currency == "INR" else avail_usd, "INR": round(avail_usd * usd_inr_rate, 2) if self.reporting_currency == "INR" else 0.0}
        else:
            if self.reporting_currency == "INR":
                half_inr = total_inr_budget / 2.0
                half_usd = half_inr / usd_inr_rate
                avail_usd = max(0.0, round(half_usd - usd_invested, 2))
                avail_inr = max(0.0, round(half_inr - inr_invested, 2))
                return {"USD": avail_usd, "INR": avail_inr}
            else:
                avail_usd = max(0.0, round(total_usd_budget - usd_invested, 2))
                return {"USD": avail_usd, "INR": 0.0}

    @property
    def cash_usd(self) -> float:
        return float(self.cash_balances.get("USD", 0.0))

    @property
    def cash_inr(self) -> float:
        return float(self.cash_balances.get("INR", 0.0))

    @property
    def cash_balance(self) -> float:
        """Legacy cash balance getter returning USD cash balance."""
        return float(self.cash_balances.get("USD", 0.0))

    @cash_balance.setter
    def cash_balance(self, val: float):
        self.cash_balances["USD"] = float(val)
        self.db.save_cash_balances(self.cash_balances)

    def get_consolidated_cash(self, currency: Optional[str] = None) -> float:
        """Consolidated available cash in requested or reporting currency."""
        curr = (currency or self.reporting_currency or "INR").upper()
        rate = self.fx_provider.get_rate("USD", "INR").rate
        if curr == "INR":
            return round(self.cash_inr + (self.cash_usd * rate), 2)
        else:
            return round(self.cash_usd + (self.cash_inr / rate), 2)

    @cash_balance.setter
    def cash_balance(self, val: float):
        if self.reporting_currency == "INR":
            self.cash_balances["INR"] = float(val)
        else:
            self.cash_balances["USD"] = float(val)
        self.db.save_cash_balances(self.cash_balances)

    def sync_holdings(self):
        persisted = self.db.get_holdings()
        if persisted:
            self.rebalancer.current_shares = {
                t: persisted.get(t, self.rebalancer.DEFAULT_SHARES_PER_CONSTITUENT)
                for t in self.rebalancer.tickers
            }
        else:
            self.rebalancer._initialize_shares()
            self.db.save_holdings(self.rebalancer.current_shares)

        persisted_cash_balances = self.db.get_cash_balances()
        if persisted_cash_balances and any(v > 0 for v in persisted_cash_balances.values()):
            self.cash_balances = dict(persisted_cash_balances)
        else:
            self.cash_balances = self._calculate_initial_cash(self.rebalancer.tickers, self.rebalancer.current_shares)
            self.db.save_cash_balances(self.cash_balances)

    async def initialize_clean_session(self):
        """
        Initializes a clean runtime state on application launch.
        Wipes previous transient scan state while keeping user configuration and ledger history.
        """
        async with self.lock:
            self.db.clear_scan_runtime_state()
            self.signals_log = []
            self.latest_orders = pd.DataFrame()
            self.last_updated = "Never"
            active_tickers = list(self.rebalancer.tickers)
            self.rebalancer.current_weights = {t: 1.0 / len(active_tickers) for t in active_tickers}
            self.latest_scan_coverage = {
                t: {
                    "ticker": t,
                    "company_name": self.ingestor.get_company_name(t),
                    "raw_retrieved": 0,
                    "fresh_retained": 0,
                    "rejected_stale": 0,
                    "rejected_irrelevant": 0,
                    "assigned_to_company": 0,
                    "analyzed_count": 0,
                    "signals_count": 0,
                    "feed_status": "READY",
                    "coverage_state": "NO_SCAN_EXECUTED_YET"
                }
                for t in active_tickers
            }

    async def reset_runtime(self):
        async with self.lock:
            self.db.clear_runtime_data()
            self.signals_log = []
            self.latest_orders = pd.DataFrame()
            self.last_updated = "Never"
            self.rebalancer.current_weights = {t: 1.0 / len(self.rebalancer.tickers) for t in self.rebalancer.tickers}
            self.rebalancer._initialize_shares()
            self.db.save_holdings(self.rebalancer.current_shares)
            self.cash_balances = self._calculate_initial_cash(self.rebalancer.tickers, self.rebalancer.current_shares)
            self.db.save_cash_balances(self.cash_balances)
            self.cumulative_fees = {"USD": 0.0, "INR": 0.0}
            self.db.save_cumulative_fees(self.cumulative_fees)
            self.latest_scan_coverage = {
                t: {
                    "ticker": t,
                    "company_name": self.ingestor.get_company_name(t),
                    "raw_retrieved": 0,
                    "fresh_retained": 0,
                    "rejected_stale": 0,
                    "rejected_irrelevant": 0,
                    "assigned_to_company": 0,
                    "analyzed_count": 0,
                    "signals_count": 0,
                    "feed_status": "READY",
                    "coverage_state": "NO_SCAN_EXECUTED_YET"
                }
                for t in self.rebalancer.tickers
            }

    def set_universe_selection(self, instrument_ids: List[str]):
        validated_insts = self.catalog.validate_selection(instrument_ids)
        new_ids = [inst.id for inst in validated_insts]
        new_tickers = [inst.display_ticker for inst in validated_insts]

        old_tickers = list(self.rebalancer.tickers)
        old_shares = dict(self.rebalancer.current_shares or {})
        old_prices = self.rebalancer.fetch_current_prices()

        self.selected_ids = new_ids
        self.db.save_universe_selection(new_ids)

        self.rebalancer.tickers = new_tickers
        self.rebalancer.current_weights = {t: 1.0 / len(new_tickers) for t in new_tickers}

        # 1. Invalidate previous scan signals, execution orders, and timestamps
        self.db.clear_scan_runtime_state()
        self.signals_log = []
        self.latest_orders = pd.DataFrame()
        self.last_updated = "Never"
        self.latest_scan_coverage = {
            t: {
                "ticker": t,
                "company_name": self.ingestor.get_company_name(t),
                "raw_retrieved": 0,
                "fresh_retained": 0,
                "rejected_stale": 0,
                "rejected_irrelevant": 0,
                "assigned_to_company": 0,
                "analyzed_count": 0,
                "signals_count": 0,
                "feed_status": "READY",
                "coverage_state": "NO_SCAN_EXECUTED_YET"
            }
            for t in new_tickers
        }

        # 2. Setup shares for new universe: preserve existing shares for retained constituents, seed newly added with 10 shares demo positions
        new_shares = {}
        for t in new_tickers:
            if t in old_shares and old_shares[t] is not None:
                new_shares[t] = old_shares[t]
            else:
                new_shares[t] = self.rebalancer.DEFAULT_SHARES_PER_CONSTITUENT

        self.rebalancer.current_shares = new_shares
        self.db.save_holdings(new_shares)

        # 3. Calculate cash balances for new universe preserving capital conservation
        usd_tickers_in_new = [t for t in new_tickers if (self.catalog.get_by_ticker(t) and self.catalog.get_by_ticker(t).currency == "USD") or not self.catalog.get_by_ticker(t)]
        inr_tickers_in_new = [t for t in new_tickers if (self.catalog.get_by_ticker(t) and self.catalog.get_by_ticker(t).currency == "INR")]
        val_prices = self.rebalancer.price_provider.get_valuation_prices(new_tickers)

        existing_inr_cash = float(self.cash_balances.get("INR", 0.0) or 0.0)
        usd_inr_rate = self.fx_provider.get_rate("USD", "INR").rate

        if existing_inr_cash > 0 and self.reporting_currency != "INR":
            usd_invested = sum(
                float(new_shares.get(t, 10.0) or 0.0) * float(val_prices.get(t, 100.0))
                for t in usd_tickers_in_new
            )
            inr_in_usd = round(existing_inr_cash / usd_inr_rate, 2)
            avail_usd = max(0.0, round(float(self.initial_capital) - inr_in_usd - usd_invested, 2))
            self.cash_balances = {
                "USD": avail_usd,
                "INR": existing_inr_cash
            }
        else:
            self.cash_balances = self._calculate_initial_cash(new_tickers, self.rebalancer.current_shares)

        self.db.save_cash_balances(self.cash_balances)

        return validated_insts

    def execute_fx_conversion(
        self,
        from_currency: str,
        to_currency: str,
        amount: float,
        notes: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Executes a real-time currency conversion between USD and INR with auditable provenance logging.
        Never allows conversion if source currency balance is insufficient.
        """
        from_curr = str(from_currency).strip().upper()
        to_curr = str(to_currency).strip().upper()

        if from_curr not in ("USD", "INR") or to_curr not in ("USD", "INR"):
            raise ValueError(f"Unsupported currencies: {from_curr} -> {to_curr}. Supported: USD, INR")
        if from_curr == to_curr:
            raise ValueError(f"Source and destination currencies must be distinct ({from_curr}).")
        if amount is None or amount <= 0:
            raise ValueError(f"Conversion amount must be strictly positive, got {amount}.")

        avail = float(self.cash_balances.get(from_curr, 0.0))
        if avail < amount:
            raise ValueError(
                f"Insufficient {from_curr} cash balance ({avail:,.2f}) for requested conversion of {amount:,.2f}."
            )

        fx_quote = self.fx_provider.get_rate(from_curr, to_curr)
        rate = fx_quote.rate
        to_amount = round(amount * rate, 2)

        self.cash_balances[from_curr] = round(avail - amount, 2)
        self.cash_balances[to_curr] = round(float(self.cash_balances.get(to_curr, 0.0)) + to_amount, 2)
        self.db.save_cash_balances(self.cash_balances)

        conv_id = self.db.log_fx_conversion(
            from_currency=from_curr,
            to_currency=to_curr,
            from_amount=amount,
            to_amount=to_amount,
            rate=rate,
            source=fx_quote.source,
            is_live=fx_quote.is_live,
            observation_time=fx_quote.observation_time,
            notes=notes or f"Conversion: {amount} {from_curr} -> {to_amount} {to_curr}"
        )

        return {
            "conversion_id": conv_id,
            "from_currency": from_curr,
            "to_currency": to_curr,
            "from_amount": amount,
            "to_amount": to_amount,
            "rate": rate,
            "source": fx_quote.source,
            "is_live": fx_quote.is_live,
            "is_fallback": fx_quote.is_fallback,
            "observation_time": fx_quote.observation_time,
            "cash_balances": dict(self.cash_balances)
        }

    def allocate_capital(
        self,
        usd_ratio: Optional[float] = None,
        inr_ratio: Optional[float] = None,
        usd_amount: Optional[float] = None,
        inr_amount_usd: Optional[float] = None
    ) -> Dict[str, Any]:
        """
        Explicitly allocates initial capital between USD and INR.
        Records an auditable FX conversion record when funding INR cash.
        """
        total_cap = float(self.initial_capital)
        if usd_amount is not None and inr_amount_usd is not None:
            target_usd_cap = float(usd_amount)
            target_inr_cap_usd = float(inr_amount_usd)
        elif usd_ratio is not None and inr_ratio is not None:
            target_usd_cap = round(total_cap * float(usd_ratio), 2)
            target_inr_cap_usd = round(total_cap * float(inr_ratio), 2)
        else:
            n_in = sum(1 for i_id in self.selected_ids if self.catalog.get_by_id(i_id).market == "IN")
            in_ratio = n_in / len(self.selected_ids)
            target_inr_cap_usd = round(total_cap * in_ratio, 2)
            target_usd_cap = round(total_cap - target_inr_cap_usd, 2)

        fx_quote = self.fx_provider.get_rate("USD", "INR")
        rate = fx_quote.rate
        inr_funded = round(target_inr_cap_usd * rate, 2)

        # Calculate invested portions
        prices = self.rebalancer.fetch_current_prices()
        usd_invested = sum(
            float(self.rebalancer.current_shares.get(t, 0.0) or 0.0) * (prices.get(t) or 100.0)
            for t in self.rebalancer.tickers
            if (self.catalog.get_by_ticker(t) and self.catalog.get_by_ticker(t).currency == "USD")
            or not self.catalog.get_by_ticker(t)
        )
        inr_invested = sum(
            float(self.rebalancer.current_shares.get(t, 0.0) or 0.0) * (prices.get(t) or 1000.0)
            for t in self.rebalancer.tickers
            if (self.catalog.get_by_ticker(t) and self.catalog.get_by_ticker(t).currency == "INR")
        )

        self.cash_balances = {
            "USD": max(0.0, round(target_usd_cap - usd_invested, 2)),
            "INR": max(0.0, round(inr_funded - inr_invested, 2))
        }
        self.db.save_cash_balances(self.cash_balances)

        if target_inr_cap_usd > 0:
            self.db.log_fx_conversion(
                from_currency="USD",
                to_currency="INR",
                from_amount=target_inr_cap_usd,
                to_amount=inr_funded,
                rate=rate,
                source=fx_quote.source,
                is_live=fx_quote.is_live,
                observation_time=fx_quote.observation_time,
                notes=f"Initial capital allocation ({target_usd_cap:,.2f} USD + {target_inr_cap_usd:,.2f} USD to INR)"
            )

        return {
            "status": "ok",
            "initial_capital_usd": total_cap,
            "allocated_usd": target_usd_cap,
            "allocated_inr_in_usd": target_inr_cap_usd,
            "allocated_inr": inr_funded,
            "fx_rate": rate,
            "fx_source": fx_quote.source,
            "cash_balances": dict(self.cash_balances)
        }

    async def get_lock(self):
        return self.lock

# Global singleton
state = None

def get_state() -> AppState:
    global state
    if state is None:
        state = AppState()
    return state
