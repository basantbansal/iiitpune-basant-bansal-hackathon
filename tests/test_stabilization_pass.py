import pytest
import math
import json
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.dependencies import AppState, get_state
from src.storage.db import SignalDatabase
from src.rebalancer.index_rebalancer import IndexRebalancer
from src.engine.risk_engine import RiskEngine
from src.engine.ingestion import MarketNewsIngestion
from src.engine.schemas import RiskSignal

@pytest.fixture
def isolated_db(tmp_path):
    db_file = tmp_path / "test_stabilization.db"
    return SignalDatabase(str(db_file))

# ============================================================================
# TASK 1: REBALANCER TESTS
# ============================================================================

def test_rebalancer_no_news_stocks_stay_at_baseline():
    """A constituent with no usable new signal keeps its baseline weight (10%)."""
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    r = IndexRebalancer(tickers=tickers, initial_capital=1_000_000)

    # NVDA positive, TSLA negative. Remaining 8 stocks have NO news.
    signals = [
        {"entity": "NVDA", "sentiment_score": 0.8, "impact_score": 8, "event_classification": "Product Launch"},
        {"entity": "TSLA", "sentiment_score": -0.8, "impact_score": 8, "event_classification": "Supply Chain / Operations"},
    ]

    orders = r.rebalance(signals)
    weights = r.current_weights

    # Total sum is 1.0
    assert np.isclose(sum(weights.values()), 1.0, atol=1e-5)

    # All weights are finite, non-negative, and bounded between 5% and 15%
    for t, w in weights.items():
        assert np.isfinite(w)
        assert 0.05 - 1e-5 <= w <= 0.15 + 1e-5

    # NVDA increases, TSLA decreases
    assert weights["NVDA"] > 0.10
    assert weights["TSLA"] < 0.10

    # No-news stocks stay EXACTLY at baseline 10%
    no_news_tickers = ["AAPL", "MSFT", "AMZN", "GOOGL", "META", "JPM", "JNJ", "XOM"]
    for t in no_news_tickers:
        assert np.isclose(weights[t], 0.10, atol=1e-5)

def test_apple_negative_news_does_not_raise_apple_weight():
    """Negative Apple headlines must lower (or at least never raise) Apple's weight."""
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    r = IndexRebalancer(tickers=tickers, initial_capital=1_000_000)

    signals = [
        {"entity": "AAPL", "sentiment_score": -0.6, "impact_score": 7, "event_classification": "Supply Chain / Operations"},
        {"entity": "MSFT", "sentiment_score": 0.6, "impact_score": 7, "event_classification": "Earnings & Financials"},
    ]

    r.rebalance(signals)
    weights = r.current_weights

    # Apple must strictly decrease
    assert weights["AAPL"] < 0.10
    # Microsoft must strictly increase
    assert weights["MSFT"] > 0.10
    # No-news stocks stay at baseline
    assert np.isclose(weights["NVDA"], 0.10, atol=1e-5)
    assert np.isclose(sum(weights.values()), 1.0, atol=1e-5)

def test_rebalancer_turnover_is_reasonable_for_small_signals():
    """Turnover for small signals should be modest, not overwhelming the portfolio."""
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices") as mock_prices:
        mock_prices.return_value = {t: 100.0 for t in tickers}
        r = IndexRebalancer(tickers=tickers, initial_capital=1_000_000)

        signals = [
            {"entity": "NVDA", "sentiment_score": 0.2, "impact_score": 5, "event_classification": "Product Launch"},
            {"entity": "TSLA", "sentiment_score": -0.2, "impact_score": 5, "event_classification": "Supply Chain / Operations"},
        ]

        df = r.rebalance(signals)
        total_turnover = df["Trade Value ($)"].sum()
        # For small signals, turnover should be well under 5% ($50,000) of a $1M portfolio
        assert total_turnover < 50_000.0

# ============================================================================
# TASK 2: ACCOUNTING TESTS
# ============================================================================

def test_accounting_price_change_changes_value_and_restart_preserves_holdings(isolated_db):
    """Holdings are persisted shares. Price changes change total_value; restart preserves holdings."""
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices") as mock_prices, \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        
        # Day 1: starting prices at $100/share -> $1,000,000 baseline
        mock_prices.return_value = {t: 100.0 for t in tickers}
        state1 = AppState(db=isolated_db)
        state1.sync_holdings()

        app.dependency_overrides[get_state] = lambda: state1
        client = TestClient(app)

        resp1 = client.get("/api/portfolio/metrics")
        assert resp1.status_code == 200
        assert resp1.json()["total_value"] == pytest.approx(1_000_000.0, rel=1e-3)
        assert resp1.json()["total_turnover"] == 0.0

        # Day 2: Market rally: prices rise 20% to $120/share
        mock_prices.return_value = {t: 120.0 for t in tickers}

        # Restart app with fresh state using same database
        state2 = AppState(db=isolated_db)
        state2.sync_holdings()

        # Shares must be preserved from DB
        for t in tickers:
            assert np.isclose(state2.rebalancer.current_shares[t], state1.rebalancer.current_shares[t])

        app.dependency_overrides[get_state] = lambda: state2
        resp2 = client.get("/api/portfolio/metrics")
        app.dependency_overrides.clear()

        # Value must reflect 20% price gain ($1,200,000), not reset to $1,000,000 capital
        assert resp2.json()["total_value"] == pytest.approx(1_200_000.0, rel=1e-3)

def test_accounting_transaction_cost_deducted_and_reconciles(isolated_db):
    """Trading costs (turnover * 0.0010) must be deducted from portfolio value and reconcile."""
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    with patch("src.rebalancer.price_provider.PriceProvider.get_prices") as mock_prices, \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        
        mock_prices.return_value = {t: 100.0 for t in tickers}
        state = AppState(db=isolated_db)
        
        # Simulate executed trade: $40,000 turnover
        state.latest_orders = pd.DataFrame([
            {"Ticker": "AAPL", "Action": "BUY", "Order Qty": 200.0, "Trade Value ($)": 20000.0},
            {"Ticker": "MSFT", "Action": "SELL", "Order Qty": 200.0, "Trade Value ($)": 20000.0},
        ])

        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        resp = client.get("/api/portfolio/metrics")
        app.dependency_overrides.clear()

        data = resp.json()
        assert data["total_turnover"] == 40000.0
        expected_cost = 40000.0 * 0.0010  # $40.00
        assert math.isclose(data["est_txn_cost"], expected_cost)
        
        # Reconcile: $1,000,000 gross equity minus $40 trading cost = $999,960.00
        assert math.isclose(data["total_value"], 1_000_000.0 - expected_cost, abs_tol=1e-2)

# ============================================================================
# TASK 3: INGESTION TESTS
# ============================================================================

def test_ingestion_queries_all_10_tickers_without_global_truncation():
    """All 10 constituents must be queried and returned without global 25-article cutoff."""
    ingestor = MarketNewsIngestion()
    tickers = list(ingestor.TICKER_COMPANY_MAP.keys())
    assert len(tickers) == 10

    # Build mock xml returning 2 articles per ticker
    def mock_urlopen(req, timeout=3):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"""<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
            <channel>
                <item><title>Test Headline A</title><pubDate>2026-10-06T12:00:00Z</pubDate></item>
                <item><title>Test Headline B</title><pubDate>2026-10-06T12:05:00Z</pubDate></item>
            </channel>
        </rss>"""
        mock_resp.__enter__.return_value = mock_resp
        return mock_resp

    with patch('urllib.request.urlopen', side_effect=mock_urlopen), \
         patch('os.path.exists', return_value=False):
        articles = ingestor.fetch_live_news(max_items_per_ticker=2)
        # All 10 constituents must be represented in coverage stats
        assert len(ingestor.coverage_stats) == 10
        for t in tickers:
            assert t in ingestor.coverage_stats

def test_independent_per_ticker_caps_and_multi_ticker_headline(isolated_db):
    """Enforce max_items per ticker independently; multi-ticker counts against all assigned tickers."""
    state = AppState(db=isolated_db)
    state.max_items = 2

    # Provide 3 articles for AAPL, 1 multi-ticker for AAPL + MSFT, and 1 for MSFT
    mock_articles = [
        {"headline": "Apple announces new device line A", "source": "News", "published_at": "2026-10-06T12:00:00Z"},
        {"headline": "Apple expands retail stores worldwide B", "source": "News", "published_at": "2026-10-06T12:05:00Z"},
        {"headline": "Apple warns on supply delays C", "source": "News", "published_at": "2026-10-06T12:10:00Z"},
        {"headline": "Microsoft and Apple form cross-platform AI cloud partnership", "source": "News", "published_at": "2026-10-06T12:15:00Z"},
        {"headline": "Microsoft reports record cloud revenue", "source": "News", "published_at": "2026-10-06T12:20:00Z"},
    ]

    with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=mock_articles), \
         patch("src.rebalancer.price_provider.PriceProvider.get_prices") as mock_prices:
        mock_prices.return_value = {t: 100.0 for t in state.rebalancer.tickers}

        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        resp = client.post("/api/market-scan")
        app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["stats_retrieved"] == 5
        assert "stats_ticker_assignments" in data
        assert "stats_new_signals" in data

        # Check signals created for AAPL: maximum 2 signals allowed per company
        aapl_signals = [s for s in data["new_signals"] if s["ticker"] == "AAPL"]
        assert len(aapl_signals) <= 2

# ============================================================================
# TASK 4: NLP PROVENANCE & MOCK TESTS
# ============================================================================

def test_groq_mock_positive_inference(monkeypatch):
    """Groq path returns valid positive structured signal with inference_source='groq'."""
    monkeypatch.setenv("GROQ_API_KEY", "test_key")
    
    mock_client = MagicMock()
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "sentiment": 0.85,
        "event_type": "Product Launch",
        "impact": 7,
        "confidence": 0.95,
        "evidence": "major new product unveil"
    })))]
    mock_client.chat.completions.create.return_value = mock_completion

    with patch("src.engine.risk_engine.Groq", return_value=mock_client):
        engine = RiskEngine(dataset_path="nonexistent.csv")
        sig = engine.analyze("Nvidia unveils breakthrough quantum computing chip", "NVDA")

        assert sig.inference_source == "groq"
        assert sig.sentiment_score == 0.85
        assert sig.event_classification == "Product Launch"
        assert sig.impact_score == 7
        assert sig.confidence == 0.95
        assert "groq" in sig.model_version.lower()

def test_groq_mock_negative_and_neutral_inference(monkeypatch):
    """Groq handles negative and neutral sentiment properly within schema."""
    monkeypatch.setenv("GROQ_API_KEY", "test_key")
    
    mock_client = MagicMock()
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock(message=MagicMock(content=json.dumps({
        "sentiment": -0.75,
        "event_type": "Credit Event",
        "impact": 9,
        "confidence": 0.92,
        "evidence": "rating downgrade"
    })))]
    mock_client.chat.completions.create.return_value = mock_completion

    with patch("src.engine.risk_engine.Groq", return_value=mock_client):
        engine = RiskEngine(dataset_path="nonexistent.csv")
        sig = engine.analyze("Tesla downgraded to junk debt rating", "TSLA")

        assert sig.inference_source == "groq"
        assert sig.sentiment_score == -0.75
        assert sig.event_classification == "Credit Event"
        assert sig.impact_score == 9

def test_groq_malformed_json_fallback(monkeypatch):
    """Malformed Groq JSON response triggers fallback_rules cleanly."""
    monkeypatch.setenv("GROQ_API_KEY", "test_key")
    
    mock_client = MagicMock()
    mock_completion = MagicMock()
    mock_completion.choices = [MagicMock(message=MagicMock(content="Invalid non-json response"))]
    mock_client.chat.completions.create.return_value = mock_completion

    with patch("src.engine.risk_engine.Groq", return_value=mock_client):
        engine = RiskEngine(dataset_path="nonexistent.csv")
        sig = engine.analyze("Standard earnings update headline", "MSFT")

        assert sig.inference_source == "fallback_rules"
        assert sig.model_version == "risk-engine-v1.0-deterministic"
        assert -1.0 <= sig.sentiment_score <= 1.0
        assert 1 <= sig.impact_score <= 10

def test_groq_timeout_and_rate_limit_fallback(monkeypatch):
    """Timeout or rate-limiting exceptions gracefully trigger fallback_rules."""
    monkeypatch.setenv("GROQ_API_KEY", "test_key")
    
    mock_client = MagicMock()
    mock_client.chat.completions.create.side_effect = TimeoutError("Connection timed out")

    with patch("src.engine.risk_engine.Groq", return_value=mock_client):
        engine = RiskEngine(dataset_path="nonexistent.csv")
        sig = engine.analyze("Market sentiment headline", "AAPL")

        assert sig.inference_source == "fallback_rules"
        assert sig.model_version == "risk-engine-v1.0-deterministic"

def test_missing_groq_key_uses_fallback_rules(monkeypatch):
    """Unset GROQ_API_KEY truthfully exercises fallback_rules."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    engine = RiskEngine(dataset_path="nonexistent.csv")
    sig = engine.analyze("General market commentary", "GOOGL")

    assert sig.inference_source == "fallback_rules"
    assert sig.model_version == "risk-engine-v1.0-deterministic"

# =========================================================================
# Priority 1: Labelled Fixtures & Honest Fallback NLP Tests
# =========================================================================

def test_priority1_negative_fixtures_direction(monkeypatch):
    """Assert all 8 negative test fixtures yield strictly negative sentiment."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    engine = RiskEngine(dataset_path="nonexistent.csv")
    
    negative_fixtures = [
        "Apple stock falls on report that company is cutting component orders on soft iPhone 18 Pro demand",
        "Apple Shares Dip After Report Says It's Cutting iPhone 18 Pro Component Orders",
        "Apple Stock Falls After Report of iPhone 18 Pro Production Cuts",
        "Musk Loses Trillionaire Status As SpaceX And Tesla Drop Wipes Out $36 Billion",
        "TSLA, GOOGL Stocks Lead 'Magnificent Seven' Rout - MAGS ETF On Track For Biggest Single-Day Loss This Year",
        "Johnson & Johnson (JNJ) Faces Fresh Patent Lawsuit Over Cardiology Device",
        "New Documents Add to Evidence in Climate Deception Case Against ExxonMobil",
        "Why Nvidia (NVDA) Stock Is Trading Lower Today"
    ]
    
    for headline in negative_fixtures:
        sig = engine.analyze(headline, "TEST")
        assert sig.sentiment_score < 0, f"Expected negative sentiment for: {headline}, got {sig.sentiment_score}"

def test_priority1_positive_fixtures_direction(monkeypatch):
    """Assert all 4 positive test fixtures yield strictly positive sentiment."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    engine = RiskEngine(dataset_path="nonexistent.csv")
    
    positive_fixtures = [
        "Tesla Stock Rises as Elon Musk Asserts Control Over Terafab Chip Project",
        "Needham's Laura Martin: Why Amazon stock is a buy",
        "Apple Shares Are Trading Near Record Highs. Can They Climb Further?",
        "JPMorgan Chase (JPM) Could Be 10% Undervalued As Earnings Near"
    ]
    
    for headline in positive_fixtures:
        sig = engine.analyze(headline, "TEST")
        assert sig.sentiment_score > 0, f"Expected positive sentiment for: {headline}, got {sig.sentiment_score}"

def test_priority1_neutral_fixtures(monkeypatch):
    """Assert routine announcement headlines produce neutral sentiment (|sentiment| <= 0.05)."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    engine = RiskEngine(dataset_path="nonexistent.csv")
    
    neutral_fixtures = [
        "ExxonMobil Announces Second-Quarter 2026 Results",
        "Microsoft announces quarterly earnings release date"
    ]
    
    for headline in neutral_fixtures:
        sig = engine.analyze(headline, "TEST")
        assert abs(sig.sentiment_score) <= 0.05, f"Expected neutral sentiment for: {headline}, got {sig.sentiment_score}"

def test_priority1_must_not_misclassify(monkeypatch):
    """Assert specific headlines do NOT trigger generic Geopolitical/Credit/Macro categories."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    engine = RiskEngine(dataset_path="nonexistent.csv")
    
    h1 = "Trump discloses Nvidia stock trades as he prepares to honor CEO Huang"
    sig1 = engine.analyze(h1, "NVDA")
    assert sig1.event_classification not in ["Geopolitical", "Credit Event", "Macroeconomic"], f"h1 misclassified as {sig1.event_classification}"
    
    h2 = "Trump August disclosure: Meta stock, SpaceX debt purchases"
    sig2 = engine.analyze(h2, "META")
    assert sig2.event_classification not in ["Credit Event", "Geopolitical", "Macroeconomic"], f"h2 misclassified as {sig2.event_classification}"
    
    h3 = "Microsoft Stock Has Grown Roughly 15-Fold Since Satya Nadella Became CEO... Growth Rate"
    sig3 = engine.analyze(h3, "MSFT")
    assert sig3.event_classification not in ["Macroeconomic", "Geopolitical", "Credit Event"], f"h3 misclassified as {sig3.event_classification}"

def test_priority1_fund_holdings_filtering():
    """Assert 13F fund holdings and custody position disclosure headlines are filtered."""
    from src.api.routes import is_fund_holdings_disclosure
    
    disclosures = [
        "Capital Advisors Lowers Stake in Apple Inc",
        "Capital Management LLC Decreases Holdings in Nvidia",
        "10,000 shares added to BlackRock Portfolio LLC",
        "Institutional Fund LLC Trims Position in Tesla",
        "Form 13F filing shows hedge fund cuts stake"
    ]
    for d in disclosures:
        assert is_fund_holdings_disclosure(d) is True, f"Expected disclosure to be filtered: {d}"

def test_priority1_apple_negative_news_reduces_apple_weight(monkeypatch, tmp_path):
    """Apple negative news reduces Apple target weight below baseline through market scan."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.dependencies import get_state, AppState
    from src.storage.db import SignalDatabase
    from src.rebalancer.price_provider import PriceProvider

    db_path = tmp_path / "apple_test.db"
    db = SignalDatabase(str(db_path))
    fixed_prices = {t: 100.0 for t in ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NVDA", "TSLA", "JPM", "JNJ", "XOM"]}

    controlled_news = [
        {"ticker": "AAPL", "headline": "Apple stock falls on report that company is cutting component orders on soft iPhone 18 Pro demand", "source": "Reuters", "published_at": "2026-10-11T12:00:00Z"},
        {"ticker": "NVDA", "headline": "Nvidia unveils breakthrough quantum chip with surge in revenue", "source": "Bloomberg", "published_at": "2026-10-11T12:01:00Z"}
    ]

    with patch("src.api.dependencies.SignalDatabase", lambda: db):
        with patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
            with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=controlled_news):
                state = AppState()
                app.dependency_overrides[get_state] = lambda: state
                client = TestClient(app)

                scan_res = client.post("/api/market-scan").json()
                port = client.get("/api/portfolio").json()
                port_dict = {p["ticker"]: p for p in port}

                # Apple weight strictly below baseline (10%)
                assert port_dict["AAPL"]["target_weight"] < 0.10, f"Expected AAPL target weight < 0.10, got {port_dict['AAPL']['target_weight']}"
                # Nvidia weight strictly above baseline
                assert port_dict["NVDA"]["target_weight"] > 0.10
                # Constituent without news stays at baseline
                assert pytest.approx(port_dict["MSFT"]["target_weight"], abs=1e-4) == 0.10
                app.dependency_overrides.clear()

# =========================================================================
# Priority 2: Groq Model Discovery & Caching Tests
# =========================================================================

def test_priority2_groq_model_discovery():
    """Assert discover_groq_model chooses the highest preference model available."""
    from src.engine.risk_engine import discover_groq_model, _GROQ_MODEL_CACHE
    _GROQ_MODEL_CACHE.clear()

    class MockModel:
        def __init__(self, id_):
            self.id = id_

    class MockClient:
        class models:
            @staticmethod
            def list():
                class Resp:
                    data = [MockModel("some-other-model"), MockModel("llama-3.3-70b-versatile"), MockModel("llama-3.1-8b-instant")]
                return Resp()

    chosen = discover_groq_model(MockClient())
    assert chosen == "llama-3.3-70b-versatile"
    _GROQ_MODEL_CACHE.clear()

# =========================================================================
# Priority 3 & 4: Trader Details Table & Auditable Stress Test Invariant
# =========================================================================

def test_priority3_trader_portfolio_fields(tmp_path):
    """Assert portfolio endpoint returns rich trader details."""
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.dependencies import get_state, AppState
    from src.storage.db import SignalDatabase
    from src.rebalancer.price_provider import PriceProvider

    db_path = tmp_path / "trader_test.db"
    db = SignalDatabase(str(db_path))
    fixed_prices = {t: 100.0 for t in ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NVDA", "TSLA", "JPM", "JNJ", "XOM"]}

    with patch("src.api.dependencies.SignalDatabase", lambda: db):
        with patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
            state = AppState()
            app.dependency_overrides[get_state] = lambda: state
            client = TestClient(app)

            port = client.get("/api/portfolio").json()
            assert len(port) == 10
            sample = port[0]
            required_keys = ["ticker", "price", "target_weight", "baseline_weight", "signed_delta_pct",
                             "current_shares", "target_shares", "action", "order_qty", "trade_value", "est_fee", "net_sentiment", "driving_headline"]
            for k in required_keys:
                assert k in sample, f"Missing key {k} in portfolio item"
            app.dependency_overrides.clear()

def test_priority4_stress_test_invariant(tmp_path):
    """Assert post_shock_value == total_value + drawdown_value and sum(asset_pnl) == total_loss for all scenarios."""
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.dependencies import get_state, AppState
    from src.storage.db import SignalDatabase
    from src.rebalancer.price_provider import PriceProvider

    db_path = tmp_path / "stress_test.db"
    db = SignalDatabase(str(db_path))
    fixed_prices = {t: 100.0 for t in ["AAPL", "MSFT", "GOOGL", "META", "AMZN", "NVDA", "TSLA", "JPM", "JNJ", "XOM"]}

    with patch("src.api.dependencies.SignalDatabase", lambda: db):
        with patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
            state = AppState()
            app.dependency_overrides[get_state] = lambda: state
            client = TestClient(app)

            scenarios_resp = client.get("/api/stress-scenarios").json()
            for sc_name in scenarios_resp.keys():
                res = client.post("/api/stress-test", json={"scenario_name": sc_name}).json()
                total_val = res["total_value"]
                drawdown_val = res["drawdown_value"]
                post_val = res["post_shock_value"]

                # Invariant 1: post = total + drawdown
                assert pytest.approx(post_val, abs=1e-2) == total_val + drawdown_val
                # Invariant 2: sum of asset P&Ls == drawdown
                sum_asset_pnl = sum(a["pnl"] for a in res["asset_results"])
                assert pytest.approx(sum_asset_pnl, abs=1e-2) == drawdown_val
                # Assets sorted by largest loss
                pnls = [a["pnl"] for a in res["asset_results"]]
                assert pnls == sorted(pnls), "Expected asset results sorted by largest loss (most negative first)"
                # Scenario assumptions returned
                assert "scenario_assumptions" in res
                assert "channel_notes" in res["scenario_assumptions"]

            app.dependency_overrides.clear()


def test_final_pass_a1_shares_reconciliation(tmp_path):
    """Test A1: pre_shares * price ~= pre-trade value, and pre_shares + signed_qty = post_shares."""
    from fastapi.testclient import TestClient
    from src.api.main import app
    from src.api.dependencies import get_state, AppState
    from src.storage.db import SignalDatabase
    from src.rebalancer.price_provider import PriceProvider

    db_path = tmp_path / "a1_test.db"
    db = SignalDatabase(str(db_path))
    fixed_prices = {
        "AAPL": 150.0, "MSFT": 250.0, "GOOGL": 100.0, "META": 200.0, "AMZN": 100.0,
        "NVDA": 100.0, "TSLA": 200.0, "JPM": 100.0, "JNJ": 100.0, "XOM": 100.0
    }

    with patch("src.api.dependencies.SignalDatabase", lambda: db), \
         patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        state = AppState()
        # Simulate active rebalance orders
        state.latest_orders = state.rebalancer.rebalance([
            {"entity": "AAPL", "sentiment_score": -0.80, "impact_score": 8, "event_classification": "Supply Chain / Operations"},
            {"entity": "MSFT", "sentiment_score": 0.80, "impact_score": 8, "event_classification": "Earnings & Financials"},
        ])
        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        portfolio = client.get("/api/portfolio").json()
        assert len(portfolio) == 10
        for row in portfolio:
            pre_sh = row["pre_shares"]
            post_sh = row["target_shares"]
            signed_qty = row["signed_qty"]
            price = row["price"]

            assert pre_sh is not None
            assert post_sh is not None
            # pre + signed_qty == post within 2 decimal rounding
            assert math.isclose(pre_sh + signed_qty, post_sh, abs_tol=0.02)
            # pre_shares * price ~= baseline value ($100,000 for $1M initial capital)
            assert math.isclose(pre_sh * price, 100_000.0, rel_tol=1e-2)

        app.dependency_overrides.clear()


def test_final_pass_b1_direction_badges():
    """Test B1: Direction badge must come from sentiment with neutral band |s| <= 0.15."""
    from src.engine.risk_engine import FinanceLexiconScorer
    from src.api.routes import get_risk_signals
    from src.api.dependencies import AppState

    state = AppState()
    state.signals_log = [
        {"entity": "AMZN", "headline": "Why Amazon stock is a buy", "sentiment_score": 0.75, "confidence": 0.85, "event_classification": "Unclassified"},
        {"entity": "TSLA", "headline": "Musk Loses Trillionaire Status As SpaceX And Tesla Drop", "sentiment_score": -0.68, "confidence": 0.85, "event_classification": "Unclassified"},
        {"entity": "XOM", "headline": "Venezuela Warning for oil markets", "sentiment_score": -0.70, "confidence": 0.80, "event_classification": "Unclassified"},
        {"entity": "GOOGL", "headline": "Routine news", "sentiment_score": 0.02, "confidence": 0.80, "event_classification": "Unclassified"},
    ]

    import asyncio
    signals = asyncio.run(get_risk_signals(state))
    badges = {s["entity"]: s["direction_badge"] for s in signals}
    assert badges["AMZN"] == "Bullish"
    assert badges["TSLA"] == "Bearish"
    assert badges["XOM"] == "Bearish"
    assert badges["GOOGL"] == "Needs Review"


def test_final_pass_b3_extended_filters():
    """Test B3: Dupree Financial 13F purchase and CME futures margins are skipped."""
    from src.api.routes import is_fund_holdings_disclosure

    assert is_fund_holdings_disclosure("20,562 JPMorgan Chase & Co. $JPM Shares Purchased by Dupree Financial Group LLC") is True
    assert is_fund_holdings_disclosure("Tesla Futures Margins adjusted by CME") is True
    assert is_fund_holdings_disclosure("Apple stock falls on report of iPhone cuts") is False


def test_final_pass_d3_reset_baseline(tmp_path):
    """Test D3: Reset Data clears runtime signals and rebuilds baseline from configured capital."""
    from src.storage.db import SignalDatabase
    from src.api.dependencies import AppState

    db_path = tmp_path / "reset_test.db"
    db = SignalDatabase(str(db_path))
    db.save_config({"initial_capital": 2_000_000.0, "alpha_tilt": 0.05, "data_mode": "Live", "max_items": 2})

    state = AppState(db=db)
    assert state.initial_capital == 2_000_000.0
    # Simulate populated signals
    state.signals_log = [{"entity": "AAPL", "headline": "Some news"}]

    import asyncio
    asyncio.run(state.reset_runtime())

    assert state.signals_log == []
    assert state.last_updated == "Never"
    assert len(state.rebalancer.current_shares) == 10
    # Baseline weight is 10% each
    for t in state.rebalancer.tickers:
        assert np.isclose(state.rebalancer.current_weights[t], 0.10)


def test_fee_rounding_and_full_reconciliation(tmp_path):
    """Test resolution of $88,445 * 0.001 = $88.445:
    Half-up rounding gives $88.45.
    Holdings = $2,000,000.00
    Cash = -$88.45
    Portfolio Value = $1,999,911.55
    Stress Test Baseline = $1,999,911.55
    Post-Shock = Pre-Shock + Sum(P&L)
    """
    from src.storage.db import SignalDatabase
    from src.api.dependencies import AppState, get_state
    from src.api.routes import round_currency
    from src.rebalancer.price_provider import PriceProvider

    # 1. Direct unit test of currency rounding policy
    assert round_currency(88445.0 * 0.0010) == 88.45
    assert round_currency(2_000_000.0 - 88.45) == 1_999_911.55

    db_path = tmp_path / "reconciliation.db"
    db = SignalDatabase(str(db_path))
    db.save_config({"initial_capital": 2_000_000.0, "alpha_tilt": 0.05, "data_mode": "Live", "max_items": 2})

    fixed_prices = {
        "AAPL": 336.64, "MSFT": 400.0, "NVDA": 100.0, "AMZN": 150.0, "GOOGL": 150.0,
        "META": 500.0, "TSLA": 200.0, "JPM": 200.0, "JNJ": 150.0, "XOM": 100.0
    }

    with patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        state = AppState(db=db)
        state.initial_capital = 2_000_000.0
        # Initialize holdings at baseline ($200,000 each = $2,000,000 total)
        state.rebalancer.initial_capital = 2_000_000.0
        state.rebalancer.current_shares = {t: 200_000.0 / fixed_prices[t] for t in state.rebalancer.tickers}

        # Simulate exact buys ($44,222.50) and sells ($44,222.50) -> gross turnover = $88,445.00
        state.latest_orders = pd.DataFrame([
            {"Ticker": "AAPL", "Action": "SELL", "Current Shares": 594.11, "Target Shares": 560.90, "Order Qty": 33.21, "Trade Value ($)": 11179.82, "Prev Weight": "10.00%", "New Weight": "9.44%"},
            {"Ticker": "MSFT", "Action": "SELL", "Current Shares": 500.00, "Target Shares": 450.00, "Order Qty": 50.00, "Trade Value ($)": 20000.00, "Prev Weight": "10.00%", "New Weight": "9.00%"},
            {"Ticker": "NVDA", "Action": "SELL", "Current Shares": 2000.0, "Target Shares": 1869.57, "Order Qty": 130.43, "Trade Value ($)": 13042.68, "Prev Weight": "10.00%", "New Weight": "9.35%"},
            {"Ticker": "AMZN", "Action": "BUY", "Current Shares": 1333.33, "Target Shares": 1480.00, "Order Qty": 146.67, "Trade Value ($)": 22000.00, "Prev Weight": "10.00%", "New Weight": "11.10%"},
            {"Ticker": "GOOGL", "Action": "BUY", "Current Shares": 1333.33, "Target Shares": 1481.48, "Order Qty": 148.15, "Trade Value ($)": 22222.50, "Prev Weight": "10.00%", "New Weight": "11.11%"},
        ])
        # Verify test setup orders gross = $88,445.00
        assert math.isclose(state.latest_orders["Trade Value ($)"].sum(), 88445.0, abs_tol=0.01)

        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        # 2. Test metrics endpoint
        metrics = client.get("/api/portfolio/metrics").json()
        assert metrics["gross_turnover"] == 88445.0
        assert metrics["one_way_turnover"] == 44222.50
        assert metrics["est_txn_cost"] == 88.45
        assert metrics["cumulative_fees_paid"] == 88.45
        assert metrics["cash_balance"] == -88.45
        assert metrics["holdings_market_value"] == 2000000.0
        assert metrics["total_value"] == 1999911.55
        # Reconciles: Holdings + Cash = Total Value
        assert math.isclose(metrics["holdings_market_value"] + metrics["cash_balance"], metrics["total_value"], abs_tol=1e-5)

        # 3. Test stress test endpoint pre-shock baseline consistency
        stress_res = client.post("/api/stress-test", json={"scenario_name": "1. 2022 Fed Tightening Shock"}).json()
        assert stress_res["total_value"] == 1999911.55
        # Pre-shock exactly matches metrics total_value
        assert stress_res["total_value"] == metrics["total_value"]
        # Invariant: Pre-shock + P&L = Post-shock
        assert math.isclose(stress_res["total_value"] + stress_res["drawdown_value"], stress_res["post_shock_value"], abs_tol=0.02)

        # 4. Test portfolio order table Pre + Signed Qty = Post
        portfolio = client.get("/api/portfolio").json()
        aapl_row = next(r for r in portfolio if r["ticker"] == "AAPL")
        assert aapl_row["action"] == "SELL"
        assert aapl_row["pre_shares"] == 594.11
        assert aapl_row["target_shares"] == 560.90
        assert aapl_row["signed_qty"] == -33.21
        assert math.isclose(aapl_row["pre_shares"] + aapl_row["signed_qty"], aapl_row["target_shares"], abs_tol=0.01)

        app.dependency_overrides.clear()

# ============================================================================
# TASK 7: PORTFOLIO ALLOCATION GRAPH & ORDER RECONCILIATION REGRESSION TESTS
# ============================================================================

def test_zero_trade_portfolio_produces_matching_baseline_and_target_weights(isolated_db):
    """A portfolio with target weights equal to baseline weights must have zero rebalance orders (all HOLD)."""
    from src.rebalancer.price_provider import PriceProvider
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    # Prices drifted arbitrarily from startup
    drifted_prices = {
        "AAPL": 350.0, "MSFT": 420.0, "NVDA": 120.0, "AMZN": 180.0, "GOOGL": 175.0,
        "META": 580.0, "TSLA": 250.0, "JPM": 220.0, "JNJ": 160.0, "XOM": 115.0
    }

    with patch.object(PriceProvider, "get_prices", return_value=drifted_prices), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        r = IndexRebalancer(tickers=tickers, initial_capital=2_000_000)
        # Empty signals / neutral news -> all target weights equal 10%
        df_orders = r.rebalance([])

        assert len(df_orders) == 10
        # Invariant: If target weights equal baseline weights, there must not be nonzero rebalance orders
        for _, row in df_orders.iterrows():
            assert row["Action"] == "HOLD"
            assert row["Order Qty"] == 0.0
            assert row["Signed Qty"] == 0.0
            assert row["Trade Value ($)"] == 0.0
            assert math.isclose(float(row["Pre Shares"]), float(row["Target Shares"]), abs_tol=1e-5)
            assert row["Prev Weight"] == "10.00%"
            assert row["New Weight"] == "10.00%"
            assert row["Delta"] == "+0.00%" or row["Delta"] == "-0.00%" or row["Delta"] == "0.00%"

        state = AppState(db=isolated_db)
        state.rebalancer = r
        state.latest_orders = df_orders

        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        portfolio_res = client.get("/api/portfolio").json()
        for item in portfolio_res:
            assert item["action"] == "HOLD"
            assert item["signed_qty"] == 0.0
            assert item["order_qty"] == 0.0
            assert item["trade_value"] == 0.0
            assert item["trade_notional"] == 0.0
            assert item["signed_delta_pct"] == 0.0
            assert item["pre_shares"] == item["target_shares"]

        metrics_res = client.get("/api/portfolio/metrics").json()
        assert metrics_res["max_asset"] == "Equal Weight"
        assert math.isclose(metrics_res["max_asset_weight"], 0.10, abs_tol=1e-5)
        assert metrics_res["gross_turnover"] == 0.0
        assert metrics_res["one_way_turnover"] == 0.0
        assert metrics_res["est_txn_cost"] == 0.0

        app.dependency_overrides.clear()

def test_nonzero_trades_cause_matching_target_weight_changes(isolated_db):
    """Nonzero trades must strictly match active target-weight changes and reconcile position valuations."""
    from src.rebalancer.price_provider import PriceProvider
    tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    fixed_prices = {t: 200.0 for t in tickers}

    with patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        r = IndexRebalancer(tickers=tickers, initial_capital=1_000_000)

        # Positive signal for NVDA, negative for TSLA
        signals = [
            {"entity": "NVDA", "sentiment_score": 0.8, "impact_score": 8, "event_classification": "Product Launch"},
            {"entity": "TSLA", "sentiment_score": -0.8, "impact_score": 8, "event_classification": "Supply Chain / Operations"},
        ]
        orders_df = r.rebalance(signals)

        nvda_row = orders_df[orders_df["Ticker"] == "NVDA"].iloc[0]
        tsla_row = orders_df[orders_df["Ticker"] == "TSLA"].iloc[0]

        # NVDA has positive tilt: BUY order, signed_qty > 0
        assert nvda_row["Action"] == "BUY"
        assert nvda_row["Signed Qty"] > 0
        assert nvda_row["Trade Value ($)"] > 0
        assert float(str(nvda_row["New Weight"]).replace("%", "")) > 10.0

        # TSLA has negative tilt: SELL order, signed_qty < 0
        assert tsla_row["Action"] == "SELL"
        assert tsla_row["Signed Qty"] < 0
        assert tsla_row["Trade Value ($)"] > 0
        assert float(str(tsla_row["New Weight"]).replace("%", "")) < 10.0

        # Invariant for all rows: Target shares = Pre shares + Signed Qty
        for _, row in orders_df.iterrows():
            assert math.isclose(row["Pre Shares"] + row["Signed Qty"], row["Target Shares"], abs_tol=0.01)

def test_target_bar_color_classification_logic():
    """Verify target bar color classification: Overweight green, Underweight red, Neutral gray."""
    def get_target_color(delta: float) -> str:
        if delta > 0.05:
            return "#2ea043"  # Overweight
        if delta < -0.05:
            return "#da3633"  # Underweight
        return "#64748b"  # Neutral

    # Overweight (> +0.05 pp)
    assert get_target_color(1.50) == "#2ea043"
    assert get_target_color(0.06) == "#2ea043"

    # Underweight (< -0.05 pp)
    assert get_target_color(-1.50) == "#da3633"
    assert get_target_color(-0.06) == "#da3633"

    # Neutral (|delta| <= 0.05 pp)
    assert get_target_color(0.0) == "#64748b"
    assert get_target_color(0.04) == "#64748b"
    assert get_target_color(-0.04) == "#64748b"

def test_largest_allocation_kpi_reflection(isolated_db):
    """Largest Target Allocation KPI must show actual maximum asset or Equal Weight when identical."""
    state = AppState(db=isolated_db)

    # 1. Equal weight case: all 10%
    state.rebalancer.current_weights = {t: 0.10 for t in state.rebalancer.tickers}
    app.dependency_overrides[get_state] = lambda: state
    client = TestClient(app)

    metrics = client.get("/api/portfolio/metrics").json()
    assert metrics["max_asset"] == "Equal Weight"
    assert math.isclose(metrics["max_asset_weight"], 0.10, abs_tol=1e-5)

    # 2. Asymmetric tilt case: NVDA is 12%, TSLA is 8%, others 10%
    state.rebalancer.current_weights = {t: 0.10 for t in state.rebalancer.tickers}
    state.rebalancer.current_weights["NVDA"] = 0.12
    state.rebalancer.current_weights["TSLA"] = 0.08

    metrics = client.get("/api/portfolio/metrics").json()
    assert metrics["max_asset"] == "NVDA"
    assert math.isclose(metrics["max_asset_weight"], 0.12, abs_tol=1e-5)

    app.dependency_overrides.clear()

def test_api_payload_and_component_invariants_consistency(isolated_db):
    """Full API payload must strictly satisfy all portfolio accounting and component invariants."""
    from src.rebalancer.price_provider import PriceProvider
    fixed_prices = {
        "AAPL": 100.0, "MSFT": 100.0, "NVDA": 100.0, "AMZN": 100.0, "GOOGL": 100.0,
        "META": 100.0, "TSLA": 100.0, "JPM": 100.0, "JNJ": 100.0, "XOM": 100.0
    }
    with patch.object(PriceProvider, "get_prices", return_value=fixed_prices), \
         patch("src.api.routes.fetch_portfolio_covariance", return_value=None):
        state = AppState(db=isolated_db)
        state.rebalancer.initial_capital = 1_000_000.0
        state.rebalancer.current_shares = {t: 1000.0 for t in state.rebalancer.tickers}

        # Simulate 1 BUY (NVDA), 1 SELL (TSLA), 8 HOLD
        state.latest_orders = pd.DataFrame([
            {"Ticker": "NVDA", "Action": "BUY", "Current Shares": 1000.0, "Target Shares": 1150.0, "Signed Qty": 150.0, "Order Qty": 150.0, "Trade Value ($)": 15000.0, "Prev Weight": "10.00%", "New Weight": "11.50%"},
            {"Ticker": "TSLA", "Action": "SELL", "Current Shares": 1000.0, "Target Shares": 850.0, "Signed Qty": -150.0, "Order Qty": 150.0, "Trade Value ($)": 15000.0, "Prev Weight": "10.00%", "New Weight": "8.50%"},
        ])
        state.rebalancer.current_weights = {t: 0.10 for t in state.rebalancer.tickers}
        state.rebalancer.current_weights["NVDA"] = 0.115
        state.rebalancer.current_weights["TSLA"] = 0.085

        app.dependency_overrides[get_state] = lambda: state
        client = TestClient(app)

        portfolio = client.get("/api/portfolio").json()
        assert len(portfolio) == 10

        total_target_value = sum(item["target_shares"] * item["price"] for item in portfolio if item["target_shares"] and item["price"])
        assert math.isclose(total_target_value, 1_000_000.0, abs_tol=1.0)

        for item in portfolio:
            # 1. Target shares = Pre shares + Signed quantity
            assert math.isclose(item["pre_shares"] + item["signed_qty"], item["target_shares"], abs_tol=0.01)
            # 2. Allocation delta = target weight - baseline weight
            expected_delta = round((item["target_weight"] - item["baseline_weight"]) * 100, 2)
            assert math.isclose(item["signed_delta_pct"], expected_delta, abs_tol=0.01)
            # 3. Action matches signed qty
            if item["action"] == "BUY":
                assert item["signed_qty"] > 0
                assert item["trade_notional"] > 0
            elif item["action"] == "SELL":
                assert item["signed_qty"] < 0
                assert item["trade_notional"] < 0
            else:
                assert item["action"] == "HOLD"
                assert item["signed_qty"] == 0.0
                assert item["trade_notional"] == 0.0
            # 4. Target position value and target weight reconcile to total target valuation
            pos_val = item["target_shares"] * item["price"]
            implied_weight = pos_val / total_target_value
            assert math.isclose(implied_weight, item["target_weight"], abs_tol=0.01)

        # Largest allocation KPI reconciles to NVDA
        metrics = client.get("/api/portfolio/metrics").json()
        assert metrics["max_asset"] == "NVDA"
        assert math.isclose(metrics["max_asset_weight"], 0.115, abs_tol=1e-4)

        app.dependency_overrides.clear()



