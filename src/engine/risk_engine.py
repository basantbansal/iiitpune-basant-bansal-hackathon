import os
import re
from typing import Tuple, List
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

from src.engine.schemas import RiskSignal


class RiskEngine:

    def __init__(self, dataset_path: str = "data/all-data.csv"):
        self.base_severities = {
            "Credit Event": 9.0,
            "Geopolitical": 8.0,
            "Macroeconomic": 7.5,
            "Merger and Acquisition": 5.5,
            "Product Launch": 3.5,
        }

        self.event_patterns = {
            "Credit Event": [
                r"\bdefault\b",
                r"\bdowngrade\b",
                r"\bbankruptcy\b",
                r"\binsolven\w*\b",
                r"\bdebt\b",
                r"\blawsuit\b",
            ],
            "Geopolitical": [
                r"\bwar\b",
                r"\bsanctions?\b",
                r"\btariff\b",
                r"\bgeopolitical\b",
                r"\bconflict\b",
                r"\btrade war\b",
            ],
            "Macroeconomic": [
                r"\binflation\b",
                r"\bcpi\b",
                r"\bfed\b",
                r"\brates?\b",
                r"\bgdp\b",
                r"\brecession\b",
                r"\byield\b",
            ],
            "Merger and Acquisition": [
                r"\bacquir\w*\b",
                r"\bmerger\b",
                r"\bbuyout\b",
                r"\btakeover\b",
                r"\bdeal\b",
            ],
            "Product Launch": [
                r"\blaunch\w*\b",
                r"\bunveil\w*\b",
                r"\bannounc\w*\b",
                r"\breleas\w*\b",
                r"\brollout\b",
            ],
        }

        self.model = self._train_model(dataset_path)

    def _train_model(self, path: str):
        if os.path.exists(path):
            try:
                df = pd.read_csv(
                    path, names=["sentiment", "headline"], encoding="latin-1"
                )
                pipeline = make_pipeline(
                    TfidfVectorizer(
                        stop_words="english",
                        ngram_range=(1, 2),
                        max_features=4000,
                    ),
                    LogisticRegression(max_iter=1000, class_weight="balanced"),
                )
                pipeline.fit(df["headline"], df["sentiment"])
                return pipeline
            except Exception:
                return None
        return None

    def _classify_event(self, text: str) -> Tuple[str, float, str]:
        lower = text.lower()
        matches = {}
        matched_spans = []

        for category, patterns in self.event_patterns.items():
            for p in patterns:
                m = re.search(p, lower)
                if m:
                    matches[category] = matches.get(category, 0) + 1
                    matched_spans.append(m.group(0))

        if not matches:
            return "Macroeconomic", 0.50, "General Market Context"

        top_event = max(matches, key=matches.get)
        confidence = min(0.95, 0.60 + 0.12 * matches[top_event])
        evidence = ", ".join(set(matched_spans[:3]))
        return top_event, confidence, evidence

    def analyze(self, text: str, entity: str = "GENERAL") -> RiskSignal:
        # 1. Sentiment Score (-1.0 to 1.0)
        if self.model:
            probs = self.model.predict_proba([text])[0]
            prob_dict = dict(zip(self.model.classes_, probs))
            sentiment_score = prob_dict.get("positive", 0.0) - prob_dict.get(
                "negative", 0.0
            )
        else:
            # Deterministic Fallback Lexicon
            pos = len(
                re.findall(
                    r"\b(surge|jump|soar|beat|profit|gain|rally|breakthrough)\b",
                    text.lower(),
                )
            )
            neg = len(
                re.findall(
                    r"\b(drop|fall|plunge|miss|loss|slump|default|probe|fraud)\b",
                    text.lower(),
                )
            )
            sentiment_score = (
                (pos - neg) / max(1, pos + neg) if (pos + neg) > 0 else 0.0
            )

        sentiment_score = round(float(sentiment_score), 4)

        # 2. Event Classification & Evidence Extraction
        event_type, event_conf, evidence = self._classify_event(text)

        # 3. Transparent Multi-Factor Impact Score (1 to 10)
        base = self.base_severities.get(event_type, 4.0)
        raw_impact = (
            0.35 * base
            + 0.35 * (abs(sentiment_score) * 10)
            + 0.30 * (event_conf * 10)
        )
        impact_score = int(round(min(10, max(1, raw_impact))))

        return RiskSignal(
            entity=entity,
            headline=text,
            sentiment_score=sentiment_score,
            event_classification=event_type,
            impact_score=impact_score,
            confidence=round(event_conf, 2),
            evidence_span=evidence,
        )