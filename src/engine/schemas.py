from dataclasses import dataclass, asdict
from typing import Optional


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
