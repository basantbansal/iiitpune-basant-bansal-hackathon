import pytest
import os
import json
from src.engine.risk_engine import RiskEngine

@pytest.fixture
def risk_engine():
    return RiskEngine(dataset_path="nonexistent.csv")

def test_confidence_deterministic_keywords(risk_engine, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    # 0 matches -> 0.50
    sig0 = risk_engine.analyze("Some generic news about a company", "AAPL")
    assert sig0.confidence == 0.50
    assert sig0.model_version == "risk-engine-v1.0-deterministic"

    # 1 match (e.g. 'earnings') -> 0.50 + 0.15*1 = 0.65
    sig1 = risk_engine.analyze("earnings are up", "AAPL")
    assert sig1.confidence == 0.65

    # 2 matches (e.g. 'earnings', 'revenue') -> 0.50 + 0.15*2 = 0.80
    sig2 = risk_engine.analyze("earnings and revenue are up", "AAPL")
    assert sig2.confidence == 0.80

def test_confidence_llm_hardcoded(risk_engine, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake_key")
    import src.engine.risk_engine

    class FakeGroq:
        def __init__(self, api_key):
            self.chat = self.FakeChat()
        class FakeChat:
            class FakeCompletions:
                def create(self, *args, **kwargs):
                    return self.FakeCompletion()
                class FakeCompletion:
                    class Choice:
                        class Message:
                            content = json.dumps({"sentiment": 0.85, "event_type": "Earnings & Financials", "evidence": "record quarterly profits"})
                        message = Message()
                    choices = [Choice()]
            def __init__(self):
                self.completions = self.FakeCompletions()

    monkeypatch.setattr(src.engine.risk_engine, "Groq", FakeGroq)

    sig = risk_engine.analyze("Earnings beat estimates", "AAPL")
    # LLM path hardcodes confidence to 0.90
    assert sig.confidence == 0.90
    assert "ensemble-groq" in sig.model_version

def test_confidence_llm_fallback_on_malformed(risk_engine, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "fake_key")
    import src.engine.risk_engine

    class FakeGroq:
        def __init__(self, api_key):
            self.chat = self.FakeChat()
        class FakeChat:
            class FakeCompletions:
                def create(self, *args, **kwargs):
                    return self.FakeCompletion()
                class FakeCompletion:
                    class Choice:
                        class Message:
                            content = "Not a JSON object"
                        message = Message()
                    choices = [Choice()]
            def __init__(self):
                self.completions = self.FakeCompletions()

    monkeypatch.setattr(src.engine.risk_engine, "Groq", FakeGroq)

    # Malformed response -> falls back to local processing
    # 'earnings' gives 1 match -> 0.65
    sig = risk_engine.analyze("earnings are up", "AAPL")
    assert sig.confidence == 0.65
    assert sig.model_version == "risk-engine-v1.0-deterministic"

def test_event_taxonomy_earnings(risk_engine, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    # Both "earnings" and "announces" match, but "earnings" (Earnings & Financials) and "quarterly" should give more weight or at least not get swamped.
    # Actually, let's see which gets matched.
    sig = risk_engine.analyze("Microsoft announces quarterly earnings release date", "MSFT")
    assert sig.event_classification == "Earnings & Financials"
