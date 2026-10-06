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