import os
import re
from typing import Tuple
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

try:
    from groq import Groq
except ImportError:
    Groq = None  # Graceful fallback if Groq is not installed

from src.engine.schemas import RiskSignal


class RiskEngine:
    def __init__(self, dataset_path: str = "data/all-data.csv"):
        self.base_severities = {
            "Credit Event": 9.0,
            "Geopolitical": 8.0,
            "Macroeconomic": 7.5,
            "Earnings & Financials": 6.0,  # Added to fix the MSFT bug
            "Merger and Acquisition": 5.5,
            "Product Launch": 3.5,
        }

        self.event_patterns = {
            "Credit Event": [
                r"\bdefault\b", r"\bdowngrade\b", r"\bbankruptcy\b",
                r"\binsolven\w*\b", r"\bdebt\b", r"\blawsuit\b",
            ],
            "Geopolitical": [
                r"\bwar\b", r"\bsanctions?\b", r"\btariff\b",
                r"\bgeopolitical\b", r"\bconflict\b", r"\btrade war\b",
            ],
            "Macroeconomic": [
                r"\binflation\b", r"\bcpi\b", r"\bfed\b",
                r"\brates?\b", r"\bgdp\b", r"\brecession\b", r"\byield\b",
            ],
            "Earnings & Financials": [
                r"\bearnings\b", r"\brevenue\b", r"\bprofits?\b",
                r"\bbeats?\b", r"\bguidance\b", r"\bestimates\b", r"\bcloud\b",
            ],
            "Merger and Acquisition": [
                r"\bacquir\w*\b", r"\bmerger\b", r"\bbuyout\b",
                r"\btakeover\b", r"\bdeal\b",
            ],
            "Product Launch": [
                r"\blaunch\w*\b", r"\bunveil\w*\b", r"\bannounc\w*\b",
                r"\breleas\w*\b", r"\brollout\b",
            ],
        }

        self.model = self._train_model(dataset_path)

    def _train_model(self, path: str):
        """Trains the fast ML pipeline if the Kaggle dataset is present."""
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
            except Exception as e:
                print(f"Warning: ML model training failed ({e}). Using lexicon fallback.")
                return None
        return None

    def _classify_event(self, text: str) -> Tuple[str, float, str]:
        """Maps text to a specific event taxonomy and extracts evidence."""
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

    def analyze(
        self, 
        text: str, 
        entity: str = "GENERAL", 
        age_hours: float = 0.0, 
        groq_api_key: str = None
    ) -> RiskSignal:
        
        # 1. Base Local Sentiment (-1.0 to 1.0)
        local_sentiment = 0.0
        if self.model:
            probs = self.model.predict_proba([text])[0]
            prob_dict = dict(zip(self.model.classes_, probs))
            local_sentiment = prob_dict.get("positive", 0.0) - prob_dict.get("negative", 0.0)
        else:
            # Enhanced lexicon to catch MSFT earnings beats
            pos = len(re.findall(r"\b(surge|jump|soar|beat|beats|profit|profits|gain|rally|breakthrough)\b", text.lower()))
            neg = len(re.findall(r"\b(drop|fall|plunge|miss|loss|slump|default|probe|fraud)\b", text.lower()))
            local_sentiment = ((pos - neg) / max(1, pos + neg)) if (pos + neg) > 0 else 0.0

        sentiment_score = local_sentiment

        # 2. Event Classification & Evidence Extraction
        event_type, event_conf, evidence = self._classify_event(text)

        # 3. GROQ HYBRID ENSEMBLE (Triggers only if API key is passed)
        if groq_api_key and Groq is not None:
            try:
                client = Groq(api_key=groq_api_key)
                prompt = f"""
                Analyze this financial headline for {entity}: "{text}"
                Return ONLY a float between -1.0 (highly negative) and 1.0 (highly positive).
                """
                completion = client.chat.completions.create(
                    model="llama3-8b-8192",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=10
                )
                
                groq_response = completion.choices[0].message.content.strip()
                match = re.search(r'-?\d+\.\d+', groq_response)
                if match:
                    groq_sentiment = float(match.group())
                    # Average the local ML model with the Groq LLM
                    sentiment_score = (local_sentiment + groq_sentiment) / 2.0
                    # Boost confidence due to dual-model corroboration
                    event_conf = min(0.99, event_conf + 0.15) 
            except Exception as e:
                print(f"Groq API failed, falling back to local ML: {e}")

        sentiment_score = round(float(sentiment_score), 4)

        # 4. Multi-Factor Impact Score (1 to 10)
        base = self.base_severities.get(event_type, 4.0)
        raw_impact = (
            0.35 * base
            + 0.35 * (abs(sentiment_score) * 10)
            + 0.30 * (event_conf * 10)
        )
        
        # 5. TIME DECAY (Half-life of 24 hours)
        decay_factor = (0.5 ** (age_hours / 24.0)) 
        raw_impact *= decay_factor

        impact_score = int(round(min(10, max(1, raw_impact))))

        return RiskSignal(
            entity=entity,
            headline=text,
            sentiment_score=sentiment_score,
            event_classification=event_type,
            impact_score=impact_score,
            confidence=round(event_conf, 2),
            evidence_span=evidence,
            model_version="ensemble-groq-local-v2.0" if groq_api_key else "risk-engine-v1.0-deterministic"
        )