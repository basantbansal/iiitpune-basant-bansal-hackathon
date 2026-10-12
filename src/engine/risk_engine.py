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

class FinanceLexiconScorer:
    """
    Finance-aware lexicon scorer (phrases + single terms, with negation and
    adversative clause 'despite/but' weighting), output clamped to [-1.0, 1.0].
    """
    NEGATIVE_PHRASES = {
        "cutting component orders": -0.85,
        "component orders cut": -0.85,
        "production cuts": -0.80,
        "production cut": -0.80,
        "patent lawsuit": -0.75,
        "climate deception": -0.80,
        "deception case": -0.75,
        "trading lower": -0.65,
        "biggest single-day loss": -0.85,
        "single-day loss": -0.75,
        "wipes out": -0.80,
        "wiped out": -0.80,
        "drops wipes out": -0.85,
        "drop wipes out": -0.85,
        "lead rout": -0.80,
        "leads rout": -0.80,
        "lead 'magnificent seven' rout": -0.85,
        "faces fresh patent lawsuit": -0.80,
        "faces lawsuit": -0.75,
        "facing lawsuit": -0.75,
        "soft demand": -0.70,
        "weak demand": -0.70,
        "profit warning": -0.85,
        "credit rating downgrade": -0.90,
        "debt downgrade": -0.85,
        "revenue miss": -0.80,
        "earnings miss": -0.80,
        "record low": -0.80,
        "record lows": -0.80,
        "cuts forecast": -0.75,
        "cut forecast": -0.75,
    }

    NEGATIVE_TERMS = {
        "falls": -0.65, "fall": -0.60, "falling": -0.60, "fell": -0.60,
        "dips": -0.55, "dip": -0.50, "dipped": -0.50, "dipping": -0.50,
        "drops": -0.65, "drop": -0.60, "dropped": -0.60, "dropping": -0.60,
        "cuts": -0.70, "cut": -0.65, "cutting": -0.70,
        "lawsuit": -0.75, "lawsuits": -0.75, "sued": -0.70,
        "rout": -0.85, "routs": -0.80,
        "loss": -0.70, "losses": -0.70, "loses": -0.65, "lose": -0.60,
        "collapse": -0.85, "collapses": -0.85, "collapsed": -0.85,
        "lower": -0.55, "lowers": -0.55,
        "warning": -0.70, "warns": -0.70, "warned": -0.70,
        "probe": -0.75, "probes": -0.75, "probed": -0.75,
        "miss": -0.65, "misses": -0.70, "missed": -0.65,
        "slump": -0.75, "slumps": -0.75, "slumped": -0.75,
        "plunge": -0.80, "plunges": -0.80, "plunged": -0.80,
        "downgrade": -0.75, "downgrades": -0.75, "downgraded": -0.75,
        "subpoena": -0.80, "fraud": -0.85, "fine": -0.70, "fined": -0.70, "fines": -0.70,
        "layoffs": -0.70, "layoff": -0.70, "shortage": -0.60, "recall": -0.70, "recalls": -0.70,
        "default": -0.90, "defaults": -0.90, "defaulted": -0.90, "bankruptcy": -0.95, "bankrupt": -0.95,
        "deception": -0.75, "weakness": -0.60, "downward": -0.55, "plunging": -0.80
    }

    POSITIVE_PHRASES = {
        "record high": 0.85,
        "record highs": 0.85,
        "buy rating": 0.75,
        "strong buy": 0.85,
        "is a buy": 0.75,
        "asserts control": 0.60,
        "all-time high": 0.85,
        "all-time highs": 0.85,
        "earnings beat": 0.80,
        "revenue beat": 0.80,
        "raised guidance": 0.80,
        "price target raised": 0.75,
        "undervalued": 0.65,
        "could be undervalued": 0.65,
        "breakthrough": 0.75,
        "blowout earnings": 0.85,
        "strong growth": 0.75,
        "solid results": 0.65,
    }

    POSITIVE_TERMS = {
        "rises": 0.65, "rise": 0.60, "rising": 0.60, "rose": 0.60,
        "upgrade": 0.75, "upgrades": 0.75, "upgraded": 0.75,
        "beats": 0.75, "beat": 0.70, "beating": 0.70,
        "growth": 0.55, "grows": 0.55, "grown": 0.55,
        "gains": 0.60, "gain": 0.55, "gained": 0.55, "gaining": 0.55,
        "surge": 0.75, "surges": 0.75, "surged": 0.75, "surging": 0.75,
        "soar": 0.75, "soars": 0.75, "soared": 0.75,
        "jump": 0.65, "jumps": 0.65, "jumped": 0.65,
        "rally": 0.70, "rallies": 0.70, "rallied": 0.70,
        "climb": 0.55, "climbs": 0.55, "climbed": 0.55,
        "bullish": 0.70, "outperform": 0.70, "undervalued": 0.65,
        "breakthrough": 0.75, "booming": 0.70, "expansion": 0.60
    }

    NEGATIONS = {"not", "no", "never", "n't", "fails", "failed", "neither", "hardly", "barely", "without"}

    @classmethod
    def score(cls, text: str) -> float:
        cleaned = re.sub(r"[^\w\s\-\']", " ", text.lower())
        tokens = cleaned.split()
        if not tokens:
            return 0.0

        lower_raw = text.lower()
        if " but " in lower_raw or " however " in lower_raw:
            parts = re.split(r"\b(?:but|however)\b", lower_raw, maxsplit=1)
            clauses = [parts[0].strip(), parts[1].strip()]
            clause_weights = [0.5, 1.2]
        elif " despite " in lower_raw or " although " in lower_raw:
            parts = re.split(r"\b(?:despite|although)\b", lower_raw, maxsplit=1)
            clauses = [parts[0].strip(), parts[1].strip()]
            clause_weights = [1.0, 0.3]
        else:
            clauses = [lower_raw]
            clause_weights = [1.0]

        total_score = 0.0
        total_w = sum(clause_weights)

        for clause_text, c_weight in zip(clauses, clause_weights):
            c_score = cls._score_clause(clause_text)
            total_score += c_score * c_weight

        final_score = total_score / total_w
        return max(-1.0, min(1.0, round(final_score, 4)))

    @classmethod
    def _score_clause(cls, clause: str) -> float:
        scores = []
        masked_clause = clause

        # 1. Negative phrases
        for phrase, val in cls.NEGATIVE_PHRASES.items():
            if phrase in masked_clause:
                scores.append(val)
                masked_clause = masked_clause.replace(phrase, " ")

        # 2. Positive phrases
        for phrase, val in cls.POSITIVE_PHRASES.items():
            if phrase in masked_clause:
                scores.append(val)
                masked_clause = masked_clause.replace(phrase, " ")

        # 3. Individual words
        words = re.findall(r"\b[\w\-']+\b", masked_clause)
        for i, word in enumerate(words):
            val = None
            if word in cls.NEGATIVE_TERMS:
                val = cls.NEGATIVE_TERMS[word]
            elif word in cls.POSITIVE_TERMS:
                val = cls.POSITIVE_TERMS[word]

            if val is not None:
                prev_window = words[max(0, i-3):i]
                has_neg = any(
                    any(neg in w for neg in cls.NEGATIONS)
                    for w in prev_window
                )
                if has_neg:
                    if val > 0:
                        val = -0.7 * val
                    else:
                        val = 0.3 * abs(val)
                scores.append(val)

        if not scores:
            return 0.0

        avg = sum(scores) / len(scores)
        return max(-1.0, min(1.0, avg))


_GROQ_MODEL_CACHE = {}

def discover_groq_model(client, env_override: str = None) -> str:
    """
    Discovers available Groq chat model via client.models.list() cached once.
    Falls back gracefully if models.list() fails.
    """
    if env_override:
        return env_override
    global _GROQ_MODEL_CACHE
    if "model" in _GROQ_MODEL_CACHE:
        return _GROQ_MODEL_CACHE["model"]

    preference = [
        "llama-3.3-70b-versatile",
        "llama-3.1-8b-instant",
        "llama-3.1-70b-versatile",
        "llama3-70b-8192",
        "llama3-8b-8192",
        "mixtral-8x7b-32768",
        "qwen/qwen3.8-27b",
        "openai/gpt-oss-120b",
        "openai/gpt-oss-20b",
    ]
    try:
        if hasattr(client, "models") and hasattr(client.models, "list"):
            resp = client.models.list()
            data = resp.data if hasattr(resp, "data") else resp
            avail_ids = set()
            for m in data:
                mid = m.id if hasattr(m, "id") else (m.get("id") if isinstance(m, dict) else str(m))
                if mid:
                    avail_ids.add(mid)
            for p in preference:
                if p in avail_ids:
                    _GROQ_MODEL_CACHE["model"] = p
                    return p
            # Fallback to any general text-generation model
            for mid in avail_ids:
                m_low = mid.lower()
                if not any(x in m_low for x in ["whisper", "guard", "audio", "embed"]):
                    _GROQ_MODEL_CACHE["model"] = mid
                    return mid
    except Exception as e:
        safe_msg = str(e)[:80]
        print(f"[RiskEngine] Groq model listing fallback: {type(e).__name__} ({safe_msg})")

    chosen = "llama-3.3-70b-versatile"
    _GROQ_MODEL_CACHE["model"] = chosen
    return chosen


class RiskEngine:
    def __init__(self, dataset_path: str = "data/synthetic_demo_data.csv"):
        groq_key = os.environ.get("GROQ_API_KEY", "")
        if not groq_key or not groq_key.strip():
            self.groq_available = False
            self.groq_reason = "no key (GROQ_API_KEY unset in environment)"
        elif Groq is None:
            self.groq_available = False
            self.groq_reason = "sdk missing (groq package not installed)"
        else:
            self.groq_available = True
            self.groq_reason = "configured and active"

        self.base_severities = {
            "Credit Event": 9.0,
            "Geopolitical": 8.0,
            "Macroeconomic": 7.5,
            "Earnings & Financials": 6.0,
            "Regulatory / Legal": 7.0,
            "Merger and Acquisition": 5.5,
            "Merger/Acquisition": 5.5,
            "Cybersecurity / Operational Incident": 8.5,
            "Supply Chain / Operations": 6.0,
            "Product Launch": 3.5,
            "Guidance / Outlook": 5.0,
            "Analyst Action": 3.0,
            "Market Sentiment": 4.0,
            "Unclassified / Needs Review": None,
        }

        self.event_patterns = {
            "Credit Event": [
                r"\bdefault\w*\b",
                r"\bbankrupt\w*\b",
                r"\binsolven\w*\b",
                r"\bdebt restructuring\b",
                r"\bdebt default\b",
                r"\bjunk rating\b",
                r"\bdistressed debt\b",
                r"\bcredit rating downgrade\b"
            ],
            "Geopolitical": [
                r"\bwar\b",
                r"\bmilitary conflict\b",
                r"\bgeopolitical conflict\b",
                r"\bgeopolitical\b",
                r"\btariffs?\b",
                r"\btrade war\b",
                r"\bsanctions?\b",
                r"\btrade embargo\b"
            ],
            "Macroeconomic": [
                r"\binflation\b",
                r"\bconsumer price index\b",
                r"\bcpi\b",
                r"\binterest rates?\b",
                r"\bcentral bank\b",
                r"\bfederal reserve\b",
                r"\bfed hike\b",
                r"\bfed cut\b",
                r"\bmonetary policy\b",
                r"\brecession\b",
                r"\bstagflation\b"
            ],
            "Earnings & Financials": [
                r"\bearnings\b",
                r"\brevenue\b",
                r"\bprofits?\b",
                r"\bdividend\b",
                r"\bfinancials\b",
                r"\bquarterly\b",
                r"\bresults\b",
                r"\bearnings date\b",
                r"\bearnings near\b",
                r"\bsecond-quarter\b",
                r"\bmargin\b"
            ],
            "Regulatory / Legal": [
                r"\blawsuit\b",
                r"\blawsuits\b",
                r"\bpatent lawsuit\b",
                r"\bprobe\b",
                r"\bprobes\b",
                r"\binvestigation\b",
                r"\bsec probe\b",
                r"\bdeception case\b",
                r"\bclimate deception\b",
                r"\bantitrust\b",
                r"\bmonopoly\b",
                r"\bfined?\b",
                r"\bsued?\b"
            ],
            "Supply Chain / Operations": [
                r"\bsupply chain\b",
                r"\bcomponent orders\b",
                r"\bproduction cuts?\b",
                r"\bproduction\b",
                r"\bshortage\b",
                r"\bfactory\b",
                r"\brecall\b",
                r"\border\w*\b",
                r"\bterafab chip project\b"
            ],
            "Market Sentiment": [
                r"\banalyst ratings?\b",
                r"\banalyst\b",
                r"\bbuy rating\b",
                r"\bsell rating\b",
                r"\bprice target\b",
                r"\bundervalued\b",
                r"\brout\b",
                r"\bselloff\b",
                r"\btrading lower\b",
                r"\btrading higher\b",
                r"\brecord high\w*\b",
                r"\bshares dip\b",
                r"\bstock falls\b",
                r"\bstock rises\b",
                r"\bstock trades?\b",
                r"\bdisclosure\b"
            ],
            "Product Launch": [
                r"\bproduct launch\b",
                r"\bunveils?\b",
                r"\bunveiling\b",
                r"\blaunch\w*\b",
                r"\bnew product\b",
                r"\bchip\b"
            ],
            "Merger/Acquisition": [
                r"\bmerger\b",
                r"\bacquisition\b",
                r"\btakeover\b",
                r"\bbuyout\b",
                r"\bm&a\b"
            ],
            "Merger and Acquisition": [
                r"\bmerger\b",
                r"\bacquisition\b",
                r"\btakeover\b",
                r"\bbuyout\b",
                r"\bm&a\b"
            ],
            "Cybersecurity / Operational Incident": [
                r"\bcyberattack\b",
                r"\bhack\w*\b",
                r"\bdata breach\b",
                r"\bransomware\b",
                r"\boutage\b"
            ],
            "Guidance / Outlook": [
                r"\bguidance\b",
                r"\bforecast\b",
                r"\boutlook\b"
            ],
            "Analyst Action": [
                r"\bupgrade\b",
                r"\bdowngrade\b",
                r"\banalyst\b"
            ]
        }

        self.model = self._train_model(dataset_path)

    def _train_model(self, path: str):
        """Robust loader for the Kaggle dataset, kept for backward compatibility."""
        if os.path.exists(path):
            try:
                df = pd.read_csv(path, encoding="latin-1", header=None)
                if str(df.iloc[0, 0]).lower() == 'sentiment':
                    df = df.iloc[1:].reset_index(drop=True)
                df = df.iloc[:, :2]
                df.columns = ["sentiment", "headline"]

                pipeline = make_pipeline(
                    TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=4000),
                    LogisticRegression(max_iter=1000, class_weight="balanced"),
                )
                pipeline.fit(df["headline"], df["sentiment"])
                return pipeline
            except Exception as e:
                return None
        return None

    def _classify_event_local(self, text: str) -> Tuple[str, float, str]:
        """Regex fallback if Groq is unavailable. Uses phrase/whole-word matching and abstains on weak evidence."""
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
            return "Unclassified / Needs Review", 0.50, "No strong event match"

        top_event = max(matches, key=matches.get)
        confidence = min(0.95, 0.50 + 0.15 * matches[top_event])
        evidence = ", ".join(set(matched_spans[:3]))
        return top_event, confidence, evidence

    def _normalize_event_category(self, raw_event: str) -> str:
        lower = (raw_event or "").lower()
        if "credit" in lower or "bankrupt" in lower or "default" in lower:
            return "Credit Event"
        elif "geo" in lower or "war" in lower or "tariff" in lower or "sanction" in lower:
            return "Geopolitical"
        elif "macro" in lower or "inflation" in lower or "rates" in lower or "cpi" in lower:
            return "Macroeconomic"
        elif "merger" in lower or "acquisition" in lower or "m&a" in lower or "buyout" in lower:
            return "Merger/Acquisition"
        elif "supply" in lower or "chain" in lower or "production" in lower or "disruption" in lower:
            return "Supply Chain / Operations"
        elif "product" in lower or "launch" in lower or "unveil" in lower or "chip" in lower:
            return "Product Launch"
        elif "earnings" in lower or "revenue" in lower or "profit" in lower:
            return "Earnings & Financials"
        elif "regulat" in lower or "lawsuit" in lower or "legal" in lower or "sec" in lower:
            return "Regulatory / Legal"
        elif "guidance" in lower or "outlook" in lower or "forecast" in lower:
            return "Guidance / Outlook"
        elif "analyst" in lower or "upgrade" in lower or "downgrade" in lower:
            return "Analyst Action"
        elif "cyber" in lower or "hack" in lower or "breach" in lower:
            return "Cybersecurity / Operational Incident"
        elif "unclass" in lower or "review" in lower or "noise" in lower:
            return "Unclassified / Needs Review"
        return raw_event if raw_event in self.base_severities else "Unclassified / Needs Review"

    def analyze(self, text: str, entity: str = "GENERAL", age_hours: float = 0.0, source: str = "News") -> RiskSignal:
        """
        Analyzes the headline text and returns a structured RiskSignal.
        Provenance is tracked truthfully via 'inference_source' ("groq" or "fallback_rules").
        On the fallback path, confidence is explicitly a keyword-heuristic estimate.
        """
        groq_api_key = os.environ.get("GROQ_API_KEY")
        inference_source = "fallback_rules"
        model_used = "risk-engine-v1.0-deterministic"
        groq_success = False

        sentiment_score = 0.0
        event_type = "Unclassified / Needs Review"
        event_conf = 0.50
        evidence = "No evidence provided"
        impact_score = None

        # 1. Attempt Groq LLM Path if configured
        if groq_api_key and Groq is not None:
            try:
                client = Groq(api_key=groq_api_key)
                env_model = os.environ.get("GROQ_MODEL")
                groq_model_name = discover_groq_model(client, env_model)
                prompt = f"""
                Analyze this financial headline concerning the entity/company {entity}: "{text}"
                Classify the primary corporate event and score the fundamental risk/sentiment for the COMPANY (not merely the short-term market stock tick):
                - Event Categories:
                  * Credit Event (default, bankruptcy, debt downgrade, spread widening: high severity)
                  * Geopolitical (war, sanctions, tariffs, trade disputes, election risk: high severity)
                  * Macroeconomic (interest rates, central bank policy, inflation, recession: medium-high severity)
                  * Earnings & Financials (quarterly revenue/profit reports, margins: medium severity)
                  * Regulatory / Legal (antitrust, lawsuits, investigations, fines: medium-high severity)
                  * Merger/Acquisition (takeovers, buyouts, divestitures: medium severity)
                  * Supply Chain / Operations (factory disruptions, component/production shortages: medium severity)
                  * Product Launch (new product unveil, major feature release: low-medium severity)
                  * Guidance / Outlook (forecast revision, production guidance: medium severity)
                  * Analyst Action (broker upgrades, price target adjustments: low severity)
                  * Unclassified / Needs Review (routine noise, general discussion)

                - Scale Anchor for Impact (1 to 10):
                  * Routine analyst opinion, minor chatter, or general commentary: 2-3
                  * Product release, earnings beat/miss, or guidance/production cut: 5-7
                  * Debt default, systemic crisis, bankruptcy, major war: 9-10

                - Sentiment Score: float strictly in range [-1.0, 1.0], where -1.0 is strongly negative for the company, 0.0 is neutral, and 1.0 is strongly positive.

                Respond ONLY with a valid JSON object in this exact schema:
                {{"sentiment": -0.5, "event_type": "Supply Chain / Operations", "impact": 6, "confidence": 0.90, "evidence": "2-5 word key snippet"}}
                """

                completion = client.chat.completions.create(
                    model=groq_model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    response_format={"type": "json_object"}
                )
                raw_content = completion.choices[0].message.content.strip()
                raw_content = raw_content.replace("```json", "").replace("```", "").strip()
                groq_data = json.loads(raw_content)

                # Parse and validate Groq fields
                parsed_sent = float(groq_data.get("sentiment", 0.0))
                sentiment_score = max(-1.0, min(1.0, round(parsed_sent, 4)))

                raw_event = str(groq_data.get("event_type", "Unclassified / Needs Review")).strip()
                event_type = self._normalize_event_category(raw_event)

                if "impact" in groq_data and groq_data["impact"] is not None:
                    impact_score = int(round(max(1, min(10, float(groq_data["impact"])))))

                evidence = str(groq_data.get("evidence", text[:40])).strip()
                event_conf = max(0.0, min(1.0, float(groq_data.get("confidence", 0.90))))

                inference_source = "groq"
                model_used = f"ensemble-groq-{groq_model_name}-json"
                groq_success = True
            except Exception as e:
                err_type = type(e).__name__
                safe_err_msg = str(e)[:100].replace(str(groq_api_key), "[REDACTED]")
                self.groq_available = False
                err_str = str(e).lower()
                if "401" in err_str or "invalid_api_key" in err_str or "unauthorized" in err_str:
                    self.groq_reason = "authentication failed (invalid API key)"
                elif "429" in err_str or "rate_limit" in err_str:
                    self.groq_reason = "rate limited (Groq 429 quota reached)"
                elif "timeout" in err_str or "timed out" in err_str:
                    self.groq_reason = "timeout (Groq request timed out)"
                elif "model_not_found" in err_str or "not accessible" in err_str:
                    self.groq_reason = "model not accessible"
                else:
                    self.groq_reason = f"inference failure ({err_type})"
                print(f"[RiskEngine] Groq inference failed ({err_type}: {safe_err_msg}); falling back to fallback_rules.")
                groq_success = False

        # 2. Deterministic Fallback Rules Path
        if not groq_success:
            inference_source = "fallback_rules"
            model_used = "risk-engine-v1.0-deterministic"
            event_type, event_conf, evidence = self._classify_event_local(text)
            sentiment_score = FinanceLexiconScorer.score(text)

        # Apply source-aware penalty for synthetic social data
        is_social = "social" in source.lower()
        if is_social:
            event_conf = event_conf * 0.5
            model_used += " (Social Penalty Applied)"

        # 3. Multi-Factor Impact Score Calculation if not provided
        if impact_score is None:
            sev = self.base_severities.get(event_type)
            base = float(sev) if isinstance(sev, (int, float)) else 3.0
            raw_impact = (
                0.35 * base
                + 0.35 * (abs(sentiment_score) * 10)
                + 0.30 * (event_conf * 10)
            )
            decay_factor = (0.5 ** (age_hours / 24.0))
            raw_impact *= decay_factor
            if is_social:
                raw_impact = min(raw_impact, 5.0)
            impact_score = int(round(min(10, max(1, raw_impact))))

        return RiskSignal(
            entity=entity,
            headline=text,
            sentiment_score=round(float(sentiment_score), 4),
            event_classification=event_type,
            impact_score=impact_score,
            confidence=round(float(event_conf), 2),
            evidence_span=evidence,
            model_version=model_used,
            inference_source=inference_source
        )
