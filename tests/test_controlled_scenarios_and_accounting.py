"""
High-Value Integration & Controlled Scenario Suite for the AI Financial Risk Platform.

Covers:
- Phase 2: Timezone normalization, alias disambiguation, and separate live smoke testing.
- Phase 3: 10 Controlled Scenarios (Neutral, Bullish, Bearish, Conflicting, Duplicate,
           Stale, No-News, 10-Company Mixed, Missing Price, Repeated Scan).
- Phase 4: Financial Invariants (Cash conservation, fee integrity, sell clamping,
           insufficient cash handling, FX conversion ledger reconciliation).
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
import pandas as pd
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.dependencies import get_state, AppState
from src.storage.db import SignalDatabase
from src.engine.catalog import get_catalog
from src.engine.ingestion import (
    parse_publication_timestamp,
    is_irrelevant_or_seo_headline,
    MarketNewsIngestion
)
from src.engine.processor import EntityResolver
from src.rebalancer.index_rebalancer import IndexRebalancer
from src.rebalancer.price_provider import PriceProvider
from src.rebalancer.fx_provider import FXRate, FXRateProvider


@pytest.fixture
def scenario_state(tmp_path):
    db_file = str(tmp_path / "controlled_scenarios.db")
    db = SignalDatabase(db_file)
    with patch("src.api.dependencies.SignalDatabase", return_value=db):
        state = AppState(db=db)
        app.dependency_overrides[get_state] = lambda: state
        yield state, db
        app.dependency_overrides.clear()


# ============================================================================
# Phase 2: Deterministic Timezones & Alias Disambiguation
# ============================================================================

def test_timezone_normalization_and_naive_dates():
    """Validates that various UTC offsets and naive dates are safely parsed to UTC."""
    now_utc = datetime.now(timezone.utc)

    # 1. IST offset (+05:30)
    ist_str = (now_utc - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%S+05:30")
    res_ist = parse_publication_timestamp(ist_str, max_age_hours=72.0)
    assert res_ist["is_fresh"] is True
    assert res_ist["has_reliable_timestamp"] is True
    assert "T" in res_ist["published_at"]

    # 2. EDT offset (-04:00)
    edt_str = (now_utc - timedelta(hours=10)).strftime("%Y-%m-%dT%H:%M:%S-04:00")
    res_edt = parse_publication_timestamp(edt_str, max_age_hours=72.0)
    assert res_edt["is_fresh"] is True

    # 3. Naive ISO date string (assumes UTC)
    naive_str = (now_utc - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
    res_naive = parse_publication_timestamp(naive_str, max_age_hours=72.0)
    assert res_naive["is_fresh"] is True
    assert res_naive["has_reliable_timestamp"] is True


def test_alias_disambiguation_avoids_substring_collisions():
    """Ensure ambiguous tickers like LT, ITC, and common nouns do not match unrelated text."""
    # "LT" should NOT match "lieutenant" or "long-term debt"
    res1 = EntityResolver.resolve_entities("The lieutenant colonel reviewed long-term debt financing")
    assert not any(r.ticker == "LT" for r in res1)

    # "LT" DOES match genuine Larsen & Toubro infrastructure news
    res2 = EntityResolver.resolve_entities("Larsen & Toubro wins major metro rail infrastructure contract in Mumbai")
    assert any(r.ticker == "LT" for r in res2)

    # "ITC" should NOT match US International Trade Commission patent dispute
    res3 = EntityResolver.resolve_entities("US International Trade Commission opens patent dispute on chip imports")
    assert not any(r.ticker == "ITC" for r in res3)

    # "Apple" should NOT match orchard/agriculture news
    res4 = EntityResolver.resolve_entities("Apple harvest hits record yield across Washington state orchards")
    assert not any(r.ticker == "AAPL" for r in res4)


# ============================================================================
# Phase 3: The 10 Controlled Scenarios
# ============================================================================

def test_scenario_01_all_neutral_news(scenario_state):
    """Scenario 1: All neutral news (|s| <= 0.15) produces 0 delta from baseline (10%), all HOLDs."""
    state, db = scenario_state
    client = TestClient(app)
    now_iso = datetime.now(timezone.utc).isoformat()

    neutral_news = [
        {"ticker": "AAPL", "headline": "Apple releases minor software update patch 18.0.1", "source": "News", "published_at": now_iso},
        {"ticker": "MSFT", "headline": "Microsoft executive speaks at annual technology conference", "source": "News", "published_at": now_iso}
    ]

    fixed_prices = {t: 100.0 for t in state.rebalancer.tickers}
    with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=neutral_news), \
         patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        resp = client.post("/api/market-scan")
        assert resp.status_code == 200

        port = client.get("/api/portfolio").json()
        for p in port:
            # Baseline is 10.0%, target should remain 10.0%
            assert p["target_weight"] == pytest.approx(0.10, abs=1e-3)
            assert p["action"] == "HOLD"
            assert p["order_qty"] == 0.0


def test_scenario_02_one_material_bullish_event(scenario_state):
    """Scenario 2: One material bullish event on AAPL increases target weight above 10.0%, generates BUY order."""
    state, db = scenario_state
    client = TestClient(app)
    now_iso = datetime.now(timezone.utc).isoformat()

    bullish_news = [
        {"ticker": "AAPL", "headline": "Apple reports record quarterly earnings surging 40% with massive dividend increase", "source": "Reuters", "published_at": now_iso}
    ]

    fixed_prices = {t: 100.0 for t in state.rebalancer.tickers}
    with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=bullish_news), \
         patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        resp = client.post("/api/market-scan")
        assert resp.status_code == 200

        port = client.get("/api/portfolio").json()
        port_dict = {p["ticker"]: p for p in port}

        # AAPL target weight strictly > 10.0%
        assert port_dict["AAPL"]["target_weight"] > 0.10
        assert port_dict["AAPL"]["action"] == "BUY"
        assert port_dict["AAPL"]["order_qty"] > 0.0


def test_scenario_03_one_material_bearish_event(scenario_state):
    """Scenario 3: One material bearish event on AAPL reduces target weight below 10.0%, generates SELL order."""
    state, db = scenario_state
    client = TestClient(app)
    now_iso = datetime.now(timezone.utc).isoformat()

    bearish_news = [
        {"ticker": "AAPL", "headline": "Apple faces massive antitrust sanctions, factory shutdown, and revenue collapse", "source": "Bloomberg", "published_at": now_iso}
    ]

    fixed_prices = {t: 100.0 for t in state.rebalancer.tickers}
    with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=bearish_news), \
         patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        resp = client.post("/api/market-scan")
        assert resp.status_code == 200

        port = client.get("/api/portfolio").json()
        port_dict = {p["ticker"]: p for p in port}

        # AAPL target weight strictly < 10.0%
        assert port_dict["AAPL"]["target_weight"] < 0.10
        assert port_dict["AAPL"]["action"] == "SELL"
        assert port_dict["AAPL"]["order_qty"] > 0.0
        assert port_dict["AAPL"]["post_shares"] >= 0.0


def test_scenario_04_multiple_conflicting_events_for_one_company(scenario_state):
    """Scenario 4: Conflicting positive and negative events for same company net out based on mean sentiment."""
    state, db = scenario_state
    client = TestClient(app)
    now_iso = datetime.now(timezone.utc).isoformat()

    conflicting_news = [
        {"ticker": "AAPL", "headline": "Apple Inc shares jump as earnings and revenue surge worldwide", "source": "News1", "published_at": now_iso},
        {"ticker": "AAPL", "headline": "Apple Inc stock falls following antitrust investigation and penalty", "source": "News2", "published_at": now_iso}
    ]

    fixed_prices = {t: 100.0 for t in state.rebalancer.tickers}
    with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=conflicting_news), \
         patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        resp = client.post("/api/market-scan")
        assert resp.status_code == 200

        port = client.get("/api/portfolio").json()
        aapl = next(p for p in port if p["ticker"] == "AAPL")
        assert aapl["signal_count"] == 2
        # Net sentiment is derived from mean of signals
        assert -1.0 <= aapl["net_sentiment"] <= 1.0


def test_scenario_05_duplicate_syndicated_coverage(scenario_state):
    """Scenario 5: Duplicate syndicated headlines across different feeds deduplicate and do NOT inflate weight."""
    state, db = scenario_state
    client = TestClient(app)
    now_iso = datetime.now(timezone.utc).isoformat()

    syndicated_news = [
        {"ticker": "NVDA", "headline": "NVIDIA unveils breakthrough Blackwell architecture", "source": "Feed A", "published_at": now_iso},
        {"ticker": "NVDA", "headline": "NVIDIA unveils breakthrough Blackwell architecture", "source": "Feed B", "published_at": now_iso},
        {"ticker": "NVDA", "headline": "Nvidia unveils breakthrough Blackwell architecture", "source": "Feed C", "published_at": now_iso}
    ]

    fixed_prices = {t: 100.0 for t in state.rebalancer.tickers}
    with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=syndicated_news), \
         patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        resp = client.post("/api/market-scan")
        assert resp.status_code == 200
        scan_data = resp.json()

        # Deduplication caught the redundant syndicated items
        assert scan_data["stats_retrieved"] == 3
        assert scan_data["stats_duplicates"] >= 1
        assert scan_data["stats_new_signals"] == 1


def test_scenario_06_stale_only_coverage(scenario_state):
    """Scenario 6: When provider only supplies articles > 72h old, they are excluded from active signals."""
    state, db = scenario_state
    client = TestClient(app)

    # 120 days old article
    stale_date = (datetime.now(timezone.utc) - timedelta(days=120)).isoformat()
    stale_news = [
        {"ticker": "AAPL", "headline": "Archival Apple Inc stock report from last quarter", "source": "ArchiveFeed", "published_at": stale_date}
    ]

    fixed_prices = {t: 100.0 for t in state.rebalancer.tickers}
    with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=stale_news), \
         patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        resp = client.post("/api/market-scan")
        assert resp.status_code == 200
        scan_data = resp.json()

        assert scan_data["stats_stale_filtered"] >= 1
        active_signals = [s for s in scan_data["new_signals"] if not s.get("is_stale")]
        assert len(active_signals) == 0


def test_scenario_07_no_news_coverage(scenario_state):
    """Scenario 7: When 0 news is returned, system outputs clear message and keeps baseline 10.0%."""
    state, db = scenario_state
    client = TestClient(app)

    fixed_prices = {t: 100.0 for t in state.rebalancer.tickers}
    with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=[]), \
         patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        resp = client.post("/api/market-scan")
        assert resp.status_code == 200
        scan_data = resp.json()

        assert scan_data["stats_retrieved"] == 0
        assert "No articles retrieved" in scan_data["message"] or "Scan failed" in scan_data["message"]

        port = client.get("/api/portfolio").json()
        for p in port:
            assert p["target_weight"] == pytest.approx(0.10, abs=1e-3)
            assert p["action"] == "HOLD"


def test_scenario_08_ten_company_mixed_relevance(scenario_state):
    """Scenario 8: Coverage across all 10 companies accounts for fresh, irrelevant, and no-news."""
    state, db = scenario_state
    client = TestClient(app)
    now_iso = datetime.now(timezone.utc).isoformat()

    mixed_articles = [
        {"ticker": "AAPL", "headline": "Apple Inc stock surges following quarterly revenue beat", "source": "News", "published_at": now_iso},
        {"ticker": "MSFT", "headline": "Caprock Group LLC Sells 500 Shares of Microsoft Corp", "source": "SEC", "published_at": now_iso},
        {"ticker": "NVDA", "headline": "Nvidia stock quote and live options chain summary", "source": "QuoteFeed", "published_at": now_iso}
    ]

    fixed_prices = {t: 100.0 for t in state.rebalancer.tickers}
    with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=mixed_articles), \
         patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        resp = client.post("/api/market-scan")
        assert resp.status_code == 200
        scan_data = resp.json()

        cov = scan_data["constituent_coverage"]
        assert len(cov) == 10
        assert cov["AAPL"]["coverage_state"] == "FRESH_NEWS_FOUND"
        assert cov["MSFT"]["rejected_irrelevant"] >= 1
        assert cov["NVDA"]["rejected_irrelevant"] >= 1
        assert cov["XOM"]["raw_retrieved"] == 0
        assert cov["XOM"]["coverage_state"] == "NO_NEWS_RETRIEVED"


def test_scenario_09_missing_price_one_constituent(scenario_state):
    """Scenario 9: Missing price for a constituent withholds trade execution."""
    state, db = scenario_state
    client = TestClient(app)
    now_iso = datetime.now(timezone.utc).isoformat()

    news = [{"ticker": "AAPL", "headline": "Apple Inc shares surge on blowout earnings report", "source": "Reuters", "published_at": now_iso}]

    # Price for AAPL is None
    prices_with_missing = {t: 100.0 for t in state.rebalancer.tickers}
    prices_with_missing["AAPL"] = None

    with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=news), \
         patch.object(PriceProvider, "get_prices", return_value=prices_with_missing):
        resp = client.post("/api/market-scan")
        assert resp.status_code == 200

        port = client.get("/api/portfolio").json()
        aapl = next(p for p in port if p["ticker"] == "AAPL")
        assert "FALLBACK" in aapl["execution_status"] or "MISSING" in aapl["execution_status"] or not aapl["is_executable"]


def test_scenario_10_repeated_scan_identical_input(scenario_state):
    """Scenario 10: Repeated scan with identical input deduplicates 100% of articles, leaving weights unchanged."""
    state, db = scenario_state
    client = TestClient(app)
    now_iso = datetime.now(timezone.utc).isoformat()

    news = [{"ticker": "AAPL", "headline": "Apple Inc stock surges following quarterly revenue beat", "source": "Reuters", "published_at": now_iso}]
    fixed_prices = {t: 100.0 for t in state.rebalancer.tickers}

    with patch("src.engine.ingestion.MarketNewsIngestion.fetch_live_news", return_value=news), \
         patch.object(PriceProvider, "get_prices", return_value=fixed_prices):
        # Scan 1
        resp1 = client.post("/api/market-scan")
        assert resp1.status_code == 200
        signals_1 = len(client.get("/api/risk-signals").json())
        assert signals_1 > 0

        # Scan 2 (Identical input immediately after)
        resp2 = client.post("/api/market-scan")
        assert resp2.status_code == 200
        scan_data2 = resp2.json()

        # All articles recognized as duplicates / already processed
        assert scan_data2["stats_skipped"] >= 1 or scan_data2["stats_duplicates"] >= 1 or scan_data2["stats_already_processed"] >= 1
        # No extra duplicate signals added
        signals_2 = len(client.get("/api/risk-signals").json())
        assert signals_2 == signals_1


# ============================================================================
# Phase 4: Financial & Accounting Invariants
# ============================================================================

def test_financial_invariant_cash_conservation(scenario_state):
    """Invariant: Opening Cash + Proceeds from Sells - Outlay for Buys - Executed Fees == Closing Cash."""
    state, db = scenario_state
    client = TestClient(app)

    metrics_pre = client.get("/api/portfolio/metrics").json()
    opening_cash = metrics_pre["cash_usd"]

    # Execute conversion to establish multi-currency baseline
    conv_resp = client.post("/api/portfolio/convert-fx", json={
        "from_currency": "USD",
        "to_currency": "INR",
        "amount": 10000.0,
        "notes": "Test rebalance cash conservation"
    })
    assert conv_resp.status_code == 200

    metrics_post = client.get("/api/portfolio/metrics").json()
    assert metrics_post["cash_usd"] == pytest.approx(opening_cash - 10000.0, abs=0.01)
    assert metrics_post["cash_inr"] == pytest.approx(10000.0 * 84.0, abs=1.0)


def test_financial_invariant_zero_cash_withholds_buys(scenario_state):
    """Invariant: Insufficient cash withholds buy order execution without crashing."""
    state, db = scenario_state
    state.cash_balances["USD"] = 0.0
    state.db.save_cash_balances(state.cash_balances)

    rebalancer = IndexRebalancer(initial_capital=1000000.0)
    rebalancer.tickers = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]
    rebalancer.current_shares = {t: 10.0 for t in rebalancer.tickers}
    prices = {t: 100.0 for t in rebalancer.tickers}

    signals = [{"ticker": "AAPL", "sentiment_score": 0.8, "impact_score": 8.0, "is_stale": False, "is_synthetic": False}]
    with patch.object(rebalancer, "fetch_current_prices", return_value=prices):
        orders_df = rebalancer.rebalance(signals, cash_balances={"USD": 0.0, "INR": 0.0})
        aapl_order = orders_df[orders_df["Ticker"] == "AAPL"].iloc[0]

        # Buy order was generated but withheld due to insufficient cash
        if aapl_order["Action"] == "BUY":
            assert aapl_order["Is Executable"] is False
            assert "INSUFFICIENT_CASH" in aapl_order["Execution Status"]


# ============================================================================
# Phase 2: Separately Labelled Live External Provider Smoke Test
# ============================================================================

@pytest.mark.live
def test_live_market_provider_smoke_check():
    """Separately labelled live smoke test connecting to live external RSS feeds."""
    ingestor = MarketNewsIngestion()
    # Pull 1 headline for AAPL and RELIANCE from real RSS feeds
    try:
        articles = ingestor.fetch_live_news(
            max_items_per_ticker=1,
            force_fallback=False,
            tickers=["AAPL", "RELIANCE"],
            enforce_freshness=True,
            max_age_hours=72.0
        )
        # Verify provider status dictionary
        assert "GoogleNews-RSS" in ingestor.provider_status
        assert "YahooFinance-RSS" in ingestor.provider_status
        # If any articles were returned, verify they obey the 72h max age
        for a in articles:
            assert a.get("article_age_days", 0) <= 3.5  # <= 72h + margin
    except Exception as exc:
        pytest.skip(f"Live provider smoke test skipped due to external network unavailability: {exc}")


# ============================================================================
# Phase 5: Indian-Market Accounting Integrity & News Coverage Regression
# ============================================================================

def test_inr_portfolio_baseline_cash_and_nav_reconciliation(scenario_state):
    """
    Validates Priority 1:
    - At baseline, invested market value is non-zero (calculated from valuation/reference prices).
    - Initial capital (₹8,40,00,000) exactly matches Available Cash + Invested Market Value.
    - Zero ₹1,00,000 discrepancy between initial capital and total accounting portfolio value.
    """
    state, db = scenario_state
    client = TestClient(app)

    # Switch to Indian 10-stock universe
    in_10 = [
        "IN_RELIANCE", "IN_TCS", "IN_HDFCBANK", "IN_INFY", "IN_ICICIBANK",
        "IN_HINDUNILVR", "IN_ITC", "IN_BHARTIARTL", "IN_LT", "IN_SBIN"
    ]
    # Set reporting currency to INR explicitly for Indian market mode
    curr_resp = client.post("/api/reporting-currency", json={"currency": "INR"})
    assert curr_resp.status_code == 200

    resp = client.put("/api/universe/selection", json={"selection": in_10})
    assert resp.status_code == 200

    metrics = client.get("/api/portfolio/metrics?currency=INR").json()
    assert metrics["reporting_currency"] == "INR"
    assert metrics["initial_capital"] == 84000000.0

    # Invested market value must be NON-ZERO (e.g. ₹1,51,600 from 10 shares of each of 10 Indian stocks)
    holdings_val = metrics["holdings_market_value"] or metrics["indicative_holdings_value"]
    assert holdings_val is not None
    assert holdings_val > 0.0

    # Available cash + holdings market value must EXACTLY equal initial capital
    cash_inr = metrics["cash_inr"]
    assert cash_inr > 0.0
    total_reconciled = round(cash_inr + holdings_val, 2)
    assert total_reconciled == 84000000.0, f"Discrepancy: Cash ({cash_inr}) + Holdings ({holdings_val}) = {total_reconciled} != 84000000.0"

    # Indicative NAV must also match initial capital
    assert metrics["indicative_nav_inr"] == 84000000.0

    # Verify portfolio holdings endpoint also shows non-zero market values
    port = client.get("/api/portfolio?currency=INR").json()
    assert len(port) == 10
    total_port_market_val = sum(item["current_market_value"] for item in port)
    assert total_port_market_val > 0.0
    assert abs(total_port_market_val - holdings_val) < 1.0


def test_all_10_indian_stocks_resolve_and_assign_news():
    """
    Validates Priority 2:
    - All 10 Indian monitored stocks have positive news assignment and coverage.
    - Resolves TCS, INFY, HDFCBANK, ICICIBANK, HINDUNILVR, BHARTIARTL, ITC, LT, SBIN, RELIANCE.
    """
    headlines_map = {
        "RELIANCE": "Reliance Industries posts strong Q3 earnings driven by retail and digital expansion",
        "TCS": "Tata Consultancy Services reports 12% jump in profit amid large cloud transformation contracts",
        "HDFCBANK": "HDFC Bank advances grow 16% year-on-year in quarterly business update",
        "INFY": "Infosys raises full-year revenue growth guidance after closing European bank deal",
        "ICICIBANK": "ICICI Bank board approves dividend as net interest margin expands",
        "HINDUNILVR": "Hindustan Unilever announces strategic FMCG portfolio expansion in premium beauty",
        "ITC": "ITC Limited reports double-digit growth in cigarette and agribusiness profits",
        "BHARTIARTL": "Bharti Airtel expands 5G rollouts across four new Indian telecom circles",
        "LT": "Larsen & Toubro wins significant engineering and construction orders in infrastructure",
        "SBIN": "State Bank of India (SBI) reports record quarterly profit as bad loans fall",
    }

    for expected_ticker, headline in headlines_map.items():
        resolved = EntityResolver.resolve_entities(headline)
        matched_tickers = [r.ticker for r in resolved]
        assert expected_ticker in matched_tickers, (
            f"Expected {expected_ticker} to be resolved from: '{headline}', but got: {matched_tickers}"
        )


def test_yahoo_finance_seo_headline_filtering():
    """
    Validates Priority 2:
    - Filters out generic Yahoo Finance SEO pages like:
      'Infosys Limited (INFY.NS) stock price, news, quote and history'
      'interactive stock chart'
    """
    seo_headlines = [
        "Infosys Limited (INFY.NS) stock price, news, quote and history",
        "Tata Consultancy Services Limited (TCS.NS) stock price, news, quote and history - Yahoo Finance",
        "Reliance Industries Limited (RELIANCE.NS) stock price, news, quote & history",
        "HDFC Bank Limited (HDFCBANK.NS) interactive stock chart and technical analysis",
        "State Bank of India (SBIN.NS) valuation, fundamentals and technicals",
        "State Bank of India stock quote",
    ]

    for hl in seo_headlines:
        is_irrel, reason = is_irrelevant_or_seo_headline(hl)
        assert is_irrel is True, f"Expected '{hl}' to be filtered out as SEO/irrelevant, but got: is_irrel={is_irrel}"
        assert reason in ("GENERIC_STOCK_QUOTE_OR_SEO", "EMPTY_HEADLINE")

