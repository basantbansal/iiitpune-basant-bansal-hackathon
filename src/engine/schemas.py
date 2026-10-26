from dataclasses import dataclass, asdict
from typing import Optional
import math
from datetime import datetime


@dataclass(frozen=True)
class RiskSignal:
    entity: str
    headline: str
    sentiment_score: float  # [-1.0, 1.0]
    event_classification: str  # Macro, Geo, Credit, M&A, Product Launch
    impact_score: int  # [1, 10]
    confidence: float  # [0.0, 1.0]
    evidence_span: str  # Traceability snippet
    model_version: str = "risk-engine-v1.0-deterministic"
    inference_source: str = "fallback_rules"
    is_shared_headline: bool = False

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class CreditExposure:
    identifier: str
    ead: float
    pd: float
    lgd: float
    risk_weight: float

    def __post_init__(self):
        if self.ead < 0:
            raise ValueError("EAD cannot be negative")
        if not (0 <= self.pd <= 1):
            raise ValueError("PD must be between 0 and 1")
        if not (0 <= self.lgd <= 1):
            raise ValueError("LGD must be between 0 and 1")
        if self.risk_weight < 0:
            raise ValueError("Risk weight cannot be negative")


@dataclass(frozen=True)
class CreditStressResult:
    identifier: str
    baseline_pd: float
    stressed_pd: float
    baseline_lgd: float
    stressed_lgd: float
    ead: float
    risk_weight: float
    baseline_ecl: float
    stressed_ecl: float
    incremental_ecl: float
    rwa: float
    cet1_impact: float

@dataclass(frozen=True)
class BacktestEvent:
    event_id: str
    event_timestamp: str
    ticker: str
    headline: str
    price_t0: float
    price_t1: float

    def __post_init__(self):
        if not self.event_id or not str(self.event_id).strip():
            raise ValueError("event_id must be a non-empty string")
        if not self.ticker or not str(self.ticker).strip():
            raise ValueError("ticker must be a non-empty string")
        if not self.headline or not str(self.headline).strip():
            raise ValueError("headline must be a non-empty string")

        if not self.event_timestamp or not str(self.event_timestamp).strip():
            raise ValueError("event_timestamp must be a non-empty string")
        try:
            datetime.fromisoformat(str(self.event_timestamp).replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("event_timestamp must be a valid timestamp")

        if self.price_t0 is None or math.isnan(self.price_t0) or math.isinf(self.price_t0) or self.price_t0 <= 0:
            raise ValueError("price_t0 must be finite and strictly positive")
        if self.price_t1 is None or math.isnan(self.price_t1) or math.isinf(self.price_t1) or self.price_t1 <= 0:
            raise ValueError("price_t1 must be finite and strictly positive")


@dataclass(frozen=True)
class Instrument:
    id: str
    name: str
    display_ticker: str
    market: str
    exchange: str
    provider_symbol: str
    currency: str
    sector: str
    aliases: tuple = ()

    VALID_MARKETS = frozenset({"US", "IN"})
    VALID_CURRENCIES = frozenset({"USD", "INR"})
    VALID_EXCHANGES = {
        "US": frozenset({"NASDAQ", "NYSE"}),
        "IN": frozenset({"NSE", "BSE"}),
    }

    def __post_init__(self):
        if not self.id or not str(self.id).strip():
            raise ValueError("Instrument id must be a non-empty string")
        if not self.name or not str(self.name).strip():
            raise ValueError("Instrument name must be a non-empty string")
        if not self.display_ticker or not str(self.display_ticker).strip():
            raise ValueError("Instrument display_ticker must be a non-empty string")
        if self.market not in self.VALID_MARKETS:
            raise ValueError(f"Invalid market '{self.market}'. Supported markets: {sorted(self.VALID_MARKETS)}")
        valid_exch = self.VALID_EXCHANGES.get(self.market, frozenset())
        if self.exchange not in valid_exch:
            raise ValueError(f"Invalid exchange '{self.exchange}' for market '{self.market}'. Valid exchanges: {sorted(valid_exch)}")
        if self.currency not in self.VALID_CURRENCIES:
            raise ValueError(f"Invalid currency '{self.currency}'. Supported currencies: {sorted(self.VALID_CURRENCIES)}")
        if not self.provider_symbol or not str(self.provider_symbol).strip():
            raise ValueError("Instrument provider_symbol must be a non-empty string")
        if not self.sector or not str(self.sector).strip():
            raise ValueError("Instrument sector must be a non-empty string")
        if isinstance(self.aliases, (list, set)):
            object.__setattr__(self, "aliases", tuple(str(a) for a in self.aliases))
        elif not isinstance(self.aliases, tuple):
            raise ValueError("Instrument aliases must be a list, tuple, or set of strings")

    def to_dict(self):
        d = asdict(self)
        d["aliases"] = list(self.aliases)
        return d
