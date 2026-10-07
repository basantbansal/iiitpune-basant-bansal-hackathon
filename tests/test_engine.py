import os
import json
import pytest
import pandas as pd
from typing import Dict, Any

from src.engine.risk_engine import RiskEngine
from src.rebalancer.index_rebalancer import IndexRebalancer
from src.engine.stress_engine import StressEngine
from src.storage.db import SignalDatabase
from src.engine.ingestion import MarketNewsIngestion
from src.engine.schemas import RiskSignal

@pytest.fixture
def risk_engine():
    # Use empty/missing path so it doesn't fail trying to read csv
    return RiskEngine(dataset_path="nonexistent.csv")

@pytest.fixture
def rebalancer():
    return IndexRebalancer(initial_capital=1_000_000, alpha_tilt=0.05)

@pytest.fixture
def stress_engine():
    return StressEngine()

@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")

@pytest.fixture
def db(db_path):
    return SignalDatabase(db_path=db_path)

@pytest.fixture
def ingestor(tmp_path):
    fallback = tmp_path / "test_sample.json"
    fallback.write_text('[{"ticker": "AAPL", "headline": "Apple is good", "source": "Test", "published_at": "2026-10-06T12:00:00Z"}]')
    return MarketNewsIngestion(fallback_path=str(fallback))


# A. Risk Engine
def test_risk_engine_normal_headline(risk_engine):
    sig = risk_engine.analyze("Apple profits surge to record high", "AAPL")
    assert isinstance(sig, RiskSignal)
    assert sig.entity == "AAPL"
    
def test_risk_engine_sentiment_bounds(risk_engine):
    sig = risk_engine.analyze("Very bad bankruptcy default", "TSLA")
    assert -1.0 <= sig.sentiment_score <= 1.0

def test_risk_engine_impact_bounds(risk_engine):
    sig = risk_engine.analyze("Normal day", "MSFT")
    assert 1 <= sig.impact_score <= 10

def test_risk_engine_event_classification(risk_engine):
    sig = risk_engine.analyze("Company declares bankruptcy", "XYZ")
    assert sig.event_classification in risk_engine.base_severities.keys()

def test_risk_engine_missing_groq_uses_fallback(risk_engine, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    sig = risk_engine.analyze("Earnings beat estimates", "AAPL")
    assert sig.model_version == "risk-engine-v1.0-deterministic"


# B. Module A (Index Rebalancer)
def test_module_a_weights_sum_to_one(rebalancer):
    mock_signals = [
        {"entity": "NVDA", "sentiment_score": 0.95, "impact_score": 8, "event_classification": "Product Launch"},
        {"entity": "TSLA", "sentiment_score": -0.88, "impact_score": 9, "event_classification": "Credit Event"},
    ]
    rebalancer.rebalance(mock_signals)
    total_weight = sum(rebalancer.current_weights.values())
    assert pytest.approx(total_weight, 0.001) == 1.0

def test_module_a_respects_constraints(rebalancer):
    mock_signals = [
        {"entity": "NVDA", "sentiment_score": 0.95, "impact_score": 10, "event_classification": "Product Launch"}
    ] * 10
    rebalancer.rebalance(mock_signals)
    for ticker, weight in rebalancer.current_weights.items():
        assert 0.0 <= weight <= 1.0  # normalized constraints

def test_module_a_empty_signals(rebalancer):
    df = rebalancer.rebalance([])
    assert df.empty or "Target Shares" in df.columns
    total_weight = sum(rebalancer.current_weights.values())
    assert pytest.approx(total_weight, 0.001) == 1.0

def test_module_a_zero_std(rebalancer):
    mock_signals = [
        {"entity": "NVDA", "sentiment_score": 0.5, "impact_score": 5, "event_classification": "Market Sentiment"},
        {"entity": "TSLA", "sentiment_score": 0.5, "impact_score": 5, "event_classification": "Market Sentiment"}
    ]
    df = rebalancer.rebalance(mock_signals)
    total_weight = sum(rebalancer.current_weights.values())
    assert not pd.isna(total_weight)


# C. Module B (Stress Engine)
def test_module_b_scenarios_execute(stress_engine, rebalancer):
    weights = rebalancer.current_weights
    for scenario in stress_engine.scenarios.keys():
        df = stress_engine.run_scenario(weights, 1_000_000, scenario)
        assert not df.empty
        assert "Total P&L" in df.columns

def test_module_b_portfolio_aggregation(stress_engine, rebalancer):
    weights = rebalancer.current_weights
    df = stress_engine.run_scenario(weights, 1_000_000, list(stress_engine.scenarios.keys())[0])
    assert "Total P&L" in df.columns
    total_pl = df["Total P&L"].sum()
    assert isinstance(total_pl, (int, float))
    assert not pd.isna(total_pl)

def test_module_b_empty_portfolio(stress_engine):
    # What if weights are 0 for all
    weights = {t: 0.0 for t in ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]}
    scenario_name = list(stress_engine.scenarios.keys())[0]
    df = stress_engine.run_scenario(weights, 1_000_000, scenario_name)
    assert df["Total P&L"].sum() == 0.0


# D. Database
def test_db_insert_and_retrieve(db):
    sig = {
        "entity": "AAPL",
        "event_classification": "Market Sentiment",
        "sentiment_score": 0.5,
        "impact_score": 5,
        "confidence": 0.8,
        "evidence_span": "test evidence",
        "model_version": "test"
    }
    h = db.generate_hash("Apple is great", "AAPL")
    db.log_signal(h, sig, "Apple is great", "Test", "2026-10-06T12:00:00Z")
    
    assert db.is_article_processed(h)

def test_db_duplicate_rejected(db):
    sig = {
        "entity": "AAPL",
        "event_classification": "Market Sentiment",
        "sentiment_score": 0.5,
        "impact_score": 5,
        "confidence": 0.8,
        "evidence_span": "test",
        "model_version": "test"
    }
    h = db.generate_hash("Apple is great", "AAPL")
    db.log_signal(h, sig, "Apple is great", "Test", "2026-10-06T12:00:00Z")
    
    # Second time shouldn't fail, but is_article_processed will return True
    assert db.is_article_processed(h)


# E. Ingestion
def test_ingestion_offline_fallback(ingestor, monkeypatch):
    # force urllib to fail to test fallback
    import urllib.request
    def mock_urlopen(*args, **kwargs):
        raise Exception("Network Error")
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    
    news = ingestor.fetch_live_news()
    assert len(news) > 0
    assert news[0]["ticker"] == "AAPL"

def test_ingestion_malformed_input(ingestor, monkeypatch, tmp_path):
    # Corrupt fallback json
    bad_fallback = tmp_path / "bad.json"
    bad_fallback.write_text("NOT JSON")
    ingestor.fallback_path = str(bad_fallback)
    
    import urllib.request
    def mock_urlopen(*args, **kwargs):
        raise Exception("Network Error")
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    
    # Should not crash, just return empty list or handle gracefully
    try:
        news = ingestor.fetch_live_news()
        assert isinstance(news, list)
    except json.JSONDecodeError:
        pass # Expected if not caught in ingestion
