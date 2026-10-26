from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class StockPrice(BaseModel):
    ticker: str
    price: float

class PortfolioMetrics(BaseModel):
    reporting_currency: str = "INR"
    reporting_currency_symbol: str = "₹"
    initial_capital: Optional[float] = 1000000.0
    initial_capital_native: Optional[float] = None
    initial_capital_reporting: Optional[float] = None
    total_value: Optional[float] = None
    total_value_usd: Optional[float] = None
    total_value_inr: Optional[float] = None
    holdings_market_value: Optional[float] = None
    holdings_market_value_usd: Optional[float] = None
    holdings_market_value_inr: Optional[float] = None
    holdings_market_value_inr_usd_equiv: Optional[float] = None
    max_asset: str = "N/A"
    max_asset_weight: float = 0.0
    total_turnover: float = 0.0
    gross_turnover: float = 0.0
    gross_turnover_reporting: float = 0.0
    gross_turnover_usd: float = 0.0
    gross_turnover_inr: float = 0.0
    one_way_turnover: float = 0.0
    one_way_turnover_pct: float = 0.0
    est_txn_cost: float = 0.0
    est_txn_cost_reporting: float = 0.0
    est_txn_cost_usd: float = 0.0
    est_txn_cost_inr: float = 0.0
    cumulative_fees_paid: float = 0.0
    cumulative_fees_paid_reporting: float = 0.0
    cumulative_fees_paid_usd: float = 0.0
    cumulative_fees_paid_inr: float = 0.0
    cash_balance: float = 0.0
    cash_reporting: float = 0.0
    cash_usd: float = 0.0
    cash_inr: float = 0.0
    cash_inr_usd_equiv: float = 0.0
    cash_usd_inr_equiv: float = 0.0
    fx_rate: float = 84.0
    fx_rate_quote: str = "USD/INR = 84.00"
    fx_rate_source: str = "Deterministic Fallback"
    fx_rate_as_of: str = "Never"
    fx_rate_observation_time: Optional[str] = None
    fx_rate_is_fallback: bool = True
    fx_rate_is_live: bool = False
    fx_rate_is_stale: bool = True
    nav_status: str = "UNAVAILABLE"
    nav_unavailability_reason: Optional[str] = None
    indicative_nav: Optional[float] = None
    indicative_nav_usd: Optional[float] = None
    indicative_nav_inr: Optional[float] = None
    indicative_holdings_value: Optional[float] = None
    indicative_holdings_value_usd: Optional[float] = None
    indicative_holdings_value_inr: Optional[float] = None
    constituent_coverage: Optional[Dict[str, Any]] = None
    last_updated: str = "No scan executed yet"
    last_scan_duration: Optional[float] = None
    baseline_volatility: Optional[float] = None
    target_volatility: Optional[float] = None

class ReportingCurrencyRequest(BaseModel):
    reporting_currency: Optional[str] = None
    currency: Optional[str] = None

    def get_currency(self) -> str:
        return (self.reporting_currency or self.currency or "INR").upper()

class FXConversionRequest(BaseModel):
    from_currency: str
    to_currency: str
    amount: float
    notes: Optional[str] = None

class CapitalAllocationRequest(BaseModel):
    usd_ratio: Optional[float] = None
    inr_ratio: Optional[float] = None
    usd_amount: Optional[float] = None
    inr_amount_usd: Optional[float] = None

class ScanResponse(BaseModel):
    message: str
    stats_retrieved: int = 0
    stats_ticker_assignments: int = 0
    stats_new_signals: int = 0
    stats_skipped: int = 0
    stats_duplicates: int = 0
    stats_already_processed: int = 0
    stats_filtered: int = 0
    stats_stale_filtered: int = 0
    stats_no_entities: int = 0
    stats_processed: int = 0
    stats_target_changes: int = 0
    stats_executed_orders: int = 0
    stats_withheld_orders: int = 0
    new_signals: List[Dict[str, Any]] = []
    latest_orders_summary: List[Dict[str, Any]] = []
    constituent_coverage: Optional[Dict[str, Any]] = None

class SignalSchema(BaseModel):
    ticker: str
    severity: Optional[float] = None
    impact_score: float
    confidence: float
    source: str
    article_hash: str
    headline: str
    published_at: str
    inference_source: Optional[str] = "fallback_rules"
    is_shared_headline: Optional[bool] = False
    is_synthetic: Optional[bool] = False
    is_unclassified: Optional[bool] = False
    article_age_days: Optional[float] = None
    direction_badge: Optional[str] = "Neutral"
    net_delta: Optional[str] = "0.00%"

class RebalanceConfig(BaseModel):
    initial_capital: float
    alpha_tilt: float
    data_mode: str
    max_items: int

class HoldingsUpdateRequest(BaseModel):
    holdings: Dict[str, float]

class StressTestResult(BaseModel):
    scenario: str
    portfolio_impact: float
    asset_impacts: Dict[str, float]

class HistoryDataPoint(BaseModel):
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: int
    sma20: Optional[float] = None
    sma50: Optional[float] = None
    benchmark_close: Optional[float] = None
