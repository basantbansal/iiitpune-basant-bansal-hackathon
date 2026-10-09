import os
import re
import json
from typing import Tuple
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline

try:
    from groq import Groq
except ImportError:
    Groq = None

from src.engine.schemas import RiskSignal

class RiskEngine:
    def __init__(self, dataset_path: str = "data/all-data.csv"):
        self.base_severities = {
            "Credit Event": 9.0,
            "Geopolitical": 8.0,
            "Macroeconomic": 7.5,
            "Earnings & Financials": 6.0,
            "Regulatory / Legal": 7.0,
            "Merger and Acquisition": 5.5,
            "Cybersecurity / Operational Incident": 8.5,
            "Supply Chain / Operations": 6.0,
            "Product Launch": 3.5,
            "Guidance / Outlook": 5.0,
            "Analyst Action": 3.0,
            "Market Sentiment": 4.0,
            "Unclassified / Needs Review": 3.0,
        }

        self.event_patterns = {
            "Credit Event": [r"\bdefault\b", r"\bdowngrade\b", r"\bbankruptcy\b", r"\bdebt\b", r"\bspreads? widening\b"],
            "Geopolitical": [r"\bwar\b", r"\btariff\b", r"\bconflict\b", r"\bsanctions\b", r"\bgeopolitical\b"],
            "Macroeconomic": [r"\binflation\b", r"\bfed\b", r"\brates?\b", r"\beconomy\b", r"\bcpi\b", r"\bmacroeconomic\b"],
            "Earnings & Financials": [r"\bearnings\b", r"\brevenue\b", r"\bprofits?\b", r"\bdividend\b", r"\bfinancials\b", r"\bquarterly\b"],
            "Regulatory / Legal": [r"\bsec\b", r"\bwarning\b", r"\blawsuit\b", r"\bsue[sd]?\b", r"\bregulator\w*\b", r"\binvestigation\b", r"\bfine[ds]?\b", r"\bantitrust\b"],
            "Merger and Acquisition": [r"\bacquir\w*\b", r"\bmerger\b", r"\bbuyout\b", r"\btakeover\b", r"\bm&a\b"],
            "Cybersecurity / Operational Incident": [r"\bhack\w*\b", r"\bbreach\b", r"\bcyberattack\b", r"\boutage\b", r"\bincident\b"],
            "Supply Chain / Operations": [r"\bsupply chain\b", r"\bshortage\b", r"\bfactory\b", r"\bproduction\b", r"\bdisruption\b"],
            "Product Launch": [r"\blaunch\w*\b", r"\bunveil\b", r"\bnew product\b", r"\breleas\w*\b"],
            "Guidance / Outlook": [r"\bguidance\b", r"\bforecast\b", r"\boutlook\b"],
            "Analyst Action": [r"\bupgrade\b", r"\bdowngrade\b", r"\btarget\b", r"\banalyst\b"],
            "Market Sentiment": [r"\bupside\b", r"\bbull\w*\b", r"\bbear\w*\b", r"\bjump\b", r"\bdrop\b", r"\bplunge\b", r"\bsoar\b"]
        }

        self.model = self._train_model(dataset_path)

    def _train_model(self, path: str):
        """Robust loader for the Kaggle dataset."""
        if os.path.exists(path):
            try:
                # Read without assuming headers to avoid misalignment
                df = pd.read_csv(path, encoding="latin-1", header=None)

                # If the first row contains the column names, drop it
                if str(df.iloc[0, 0]).lower() == 'sentiment':
                    df = df.iloc[1:].reset_index(drop=True)

                # Force only the first two columns
                df = df.iloc[:, :2]
                df.columns = ["sentiment", "headline"]

                pipeline = make_pipeline( # here
                    TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=4000),
                    LogisticRegression(max_iter=1000, class_weight="balanced"),
                )
                pipeline.fit(df["headline"], df["sentiment"])
                return pipeline
            except Exception as e:
                print(f"ML Model Training Warning: {e}. Falling back to lexicon & LLM.")
                return None
        return None

    def _classify_event_local(self, text: str) -> Tuple[str, float, str]: # this is used to classify the event type using regex patterns if Groq is unavailable
        """Regex fallback if Groq is unavailable."""
        lower = text.lower()
        matches = {}
        matched_spans = []

        for category, patterns in self.event_patterns.items(): #
            for p in patterns:
                m = re.search(p, lower)
                if m:
                    matches[category] = matches.get(category, 0) + 1
                    matched_spans.append(m.group(0))

        if not matches:
            return "Unclassified / Needs Review", 0.50, "No strong event match"

        top_event = max(matches, key=matches.get)
        confidence = min(0.95, 0.50 + 0.15 * matches[top_event])
        evidence = ", ".join(set(matched_spans[:3]))
        return top_event, confidence, evidence

    def analyze(self, text: str, entity: str = "GENERAL", age_hours: float = 0.0, source: str = "News") -> RiskSignal:
        """
        Analyzes the text and returns a RiskSignal.
        Note: The 'confidence' field is NOT a statistically calibrated probability.
        - On the deterministic fallback path, it is a heuristic based on keyword match counts.
        - On the LLM path, it is fixed to 0.90 to denote a successful parse.
        """
        groq_api_key = os.environ.get("GROQ_API_KEY")

        # 1. Base Local Processing
        event_type, event_conf, evidence = self._classify_event_local(text)

        local_sentiment = 0.0
        if self.model:
            try:
                probs = self.model.predict_proba([text])[0]
                prob_dict = dict(zip(self.model.classes_, probs))
                # Handle Kaggle's text labels: 'positive', 'negative'
                pos = prob_dict.get("positive", 0.0)
                neg = prob_dict.get("negative", 0.0)
                local_sentiment = pos - neg
            except Exception:
                pass

        sentiment_score = local_sentiment

        # 2. GROQ HYBRID ENSEMBLE (Structured JSON Extraction)
        model_used = "risk-engine-v1.0-deterministic"

        if groq_api_key and Groq is not None:
            try:
                client = Groq(api_key=groq_api_key)
                prompt = f"""
                Analyze this financial headline for the asset {entity}: "{text}"
                Classify the event into exactly one of these categories: Credit Event, Geopolitical, Macroeconomic, Earnings & Financials, Regulatory / Legal, Merger and Acquisition, Cybersecurity / Operational Incident, Supply Chain / Operations, Product Launch, Guidance / Outlook, Analyst Action, Market Sentiment, Unclassified / Needs Review.
                Provide a sentiment score between -1.0 (highly negative) and 1.0 (highly positive).
                Extract a 2-5 word evidence snippet from the headline.

                Respond ONLY with a valid JSON object in this exact format:
                {{"sentiment": 0.85, "event_type": "Earnings & Financials", "evidence": "record quarterly profits"}}
                """

                groq_model_name = os.environ.get("GROQ_MODEL", "llama-3.1-8b-instant")
                completion = client.chat.completions.create(
                    model=groq_model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    response_format={"type": "json_object"} # Forces LLaMA to return valid JSON
                )
                raw_content = completion.choices[0].message.content.strip()
                raw_content = raw_content.replace("```json", "").replace("```", "").strip()

                groq_data = json.loads(raw_content)

                # Override local metrics with the much smarter LLM metrics
                sentiment_score = float(groq_data.get("sentiment", local_sentiment))
                event_type = groq_data.get("event_type", event_type)
                evidence = groq_data.get("evidence", evidence)
                event_conf = 0.90 # High confidence due to LLM reasoning
                model_used = f"ensemble-groq-{groq_model_name}-json"

            except Exception as e:
                print(f"Groq API fallback triggered: {e}")

        sentiment_score = round(float(sentiment_score), 4)

        # Apply source-aware penalty for synthetic social data.
        # This is a conservative, uncalibrated heuristic reflecting that social media
        # is out-of-domain for our formal-news TF-IDF model.
        is_social = "social" in source.lower()
        if is_social:
            event_conf = event_conf * 0.5  # Penalize confidence for out-of-domain text
            model_used += " (Social Penalty Applied)"

        # 3. Multi-Factor Impact Score (1 to 10)
        base = self.base_severities.get(event_type, 4.0)
        raw_impact = (
            0.35 * base
            + 0.35 * (abs(sentiment_score) * 10)
            + 0.30 * (event_conf * 10)
        )

        # 4. Time Decay
        decay_factor = (0.5 ** (age_hours / 24.0))
        raw_impact *= decay_factor

        # Additional social penalty on absolute impact limits
        if is_social:
            raw_impact = min(raw_impact, 5.0)

        impact_score = int(round(min(10, max(1, raw_impact))))

        return RiskSignal(
            entity=entity,
            headline=text,
            sentiment_score=sentiment_score,
            event_classification=event_type,
            impact_score=impact_score,
            confidence=round(event_conf, 2),
            evidence_span=evidence,
            model_version=model_used
        )
