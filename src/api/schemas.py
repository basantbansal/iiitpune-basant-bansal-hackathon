from pydantic import BaseModel
from typing import List, Dict, Any, Optional

class StockPrice(BaseModel):
    ticker: str
    price: float

class PortfolioMetrics(BaseModel):
    initial_capital: Optional[float] = 1000000.0
    total_value: Optional[float] = None
    holdings_market_value: Optional[float] = None
    max_asset: str = "N/A"
    max_asset_weight: float = 0.0
    total_turnover: float = 0.0
    gross_turnover: float = 0.0
    one_way_turnover: float = 0.0
    one_way_turnover_pct: float = 0.0
    est_txn_cost: float = 0.0
    cumulative_fees_paid: float = 0.0
    cash_balance: float = 0.0
    last_updated: str = "Never"
    last_scan_duration: Optional[float] = None
    baseline_volatility: Optional[float] = None
    target_volatility: Optional[float] = None

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
    new_signals: List[Dict[str, Any]] = []
    latest_orders_summary: List[Dict[str, Any]] = []

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
