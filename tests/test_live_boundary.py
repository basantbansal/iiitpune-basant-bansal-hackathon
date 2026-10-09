import pytest
from src.engine.ingestion import MarketNewsIngestion
import urllib.request

def test_live_network_failure_returns_empty(monkeypatch):
    def mock_urlopen(*args, **kwargs):
        raise Exception("Network Error")
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    ingestor = MarketNewsIngestion()
    # Live mode requested (force_fallback=False)
    news = ingestor.fetch_live_news(force_fallback=False)
    # Ensure it doesn't return fallback data (Replay-Feed), only the demo social feed if any
    assert all(item["source"] != "Replay-Feed" for item in news)
    assert all(item["source"] != "GoogleNews-RSS" for item in news)

def test_replay_mode_injects_fallback(monkeypatch):
    def mock_urlopen(*args, **kwargs):
        raise Exception("Should not be called")
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    ingestor = MarketNewsIngestion()
    # Offline Crisis Replay requested
    news = ingestor.fetch_live_news(force_fallback=True)
    # Ensure it returns fallback data
    assert len(news) > 0
    assert news[0]["source"] == "Replay-Feed"

def test_live_empty_feed(monkeypatch):
    class MockResponse:
        def read(self):
            return b""
    def mock_urlopen(*args, **kwargs):
        return MockResponse()
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    ingestor = MarketNewsIngestion()
    news = ingestor.fetch_live_news(force_fallback=False)
    assert all(item["source"] != "GoogleNews-RSS" for item in news)

def test_live_malformed_feed(monkeypatch):
    class MockResponse:
        def read(self):
            return b"This is not valid XML!"
    def mock_urlopen(*args, **kwargs):
        return MockResponse()
    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    ingestor = MarketNewsIngestion()
    news = ingestor.fetch_live_news(force_fallback=False)
    assert all(item["source"] != "GoogleNews-RSS" for item in news)
