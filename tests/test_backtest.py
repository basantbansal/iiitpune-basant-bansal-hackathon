import pytest
from unittest.mock import patch, MagicMock
import os
import tempfile
import csv
from src.validation.backtest import HistoricalBacktester
from src.engine.schemas import BacktestEvent

@pytest.fixture
def dummy_csv_data():
    return [
        {"event_id": "EVT_002", "event_timestamp": "2023-02-01T10:00:00Z", "ticker": "AAPL", "headline": "Apple is doing okay", "price_t0": "150.0", "price_t1": "155.0"},
        {"event_id": "EVT_001", "event_timestamp": "2023-01-01T10:00:00Z", "ticker": "MSFT", "headline": "Microsoft launches something", "price_t0": "250.0", "price_t1": "260.0"},
    ]

@pytest.fixture
def temp_csv_file(dummy_csv_data):
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write("# SYNTHETIC VALIDATION DATA - DETERMINISTIC REPLAY ONLY\n")
        writer = csv.DictWriter(f, fieldnames=["event_id", "event_timestamp", "ticker", "headline", "price_t0", "price_t1"])
        writer.writeheader()
        writer.writerows(dummy_csv_data)
    yield path
    os.remove(path)

def test_chronological_ordering(temp_csv_file):
    """
    Test that the backtester correctly sorts events chronologically
    to prevent look-ahead bias from out-of-order processing.
    """
    tester = HistoricalBacktester(data_path=temp_csv_file)
    events = tester.load_events()

    assert len(events) == 2
    assert events[0].event_id == "EVT_001"
    assert events[1].event_id == "EVT_002"

@patch("src.validation.backtest.RiskEngine")
def test_look_ahead_protection(mock_risk_engine_class, temp_csv_file):
    """
    Test that price_t1 is absolutely NEVER passed to the Risk Engine.
    Only the text/headline and entity should be visible to the analysis model.
    """
    mock_engine = MagicMock()
    # Ensure it returns a dummy signal so the test proceeds
    from src.engine.schemas import RiskSignal
    mock_engine.analyze.return_value = RiskSignal(
        entity="DUMMY", headline="dummy", sentiment_score=0.5,
        event_classification="Market Sentiment", impact_score=5,
        confidence=0.9, evidence_span="dummy"
    )
    mock_risk_engine_class.return_value = mock_engine

    tester = HistoricalBacktester(data_path=temp_csv_file)
    tester.run_backtest()

    # Verify that analyze was called, and strictly assert what it was called with
    # It must not contain prices.
    assert mock_engine.analyze.call_count == 2

    # First call (EVT_001 due to sorting)
    call_args_1 = mock_engine.analyze.call_args_list[0]
    assert call_args_1.kwargs["text"] == "Microsoft launches something"
    assert call_args_1.kwargs["entity"] == "MSFT"
    assert "price" not in call_args_1.kwargs
    assert "price_t1" not in call_args_1.kwargs

    # Second call (EVT_002)
    call_args_2 = mock_engine.analyze.call_args_list[1]
    assert call_args_2.kwargs["text"] == "Apple is doing okay"
    assert call_args_2.kwargs["entity"] == "AAPL"
    assert "price_t1" not in call_args_2.kwargs

def test_metrics_calculation(temp_csv_file):
    tester = HistoricalBacktester(data_path=temp_csv_file)
    metrics = tester.run_backtest()

    assert metrics["total_events"] == 2
    assert "directional_matching_rate_pct" in metrics
    assert "average_forward_return_pct" in metrics
    assert "disclaimer" in metrics
    assert "NOT evidence" in metrics["disclaimer"]

import math

def test_invalid_strings():
    with pytest.raises(ValueError, match="event_id must be a non-empty string"):
        BacktestEvent(event_id="", event_timestamp="2023-01-01T00:00:00Z", ticker="AAPL", headline="Test", price_t0=100.0, price_t1=100.0)
    with pytest.raises(ValueError, match="event_id must be a non-empty string"):
        BacktestEvent(event_id="   ", event_timestamp="2023-01-01T00:00:00Z", ticker="AAPL", headline="Test", price_t0=100.0, price_t1=100.0)
    with pytest.raises(ValueError, match="ticker must be a non-empty string"):
        BacktestEvent(event_id="EVT_001", event_timestamp="2023-01-01T00:00:00Z", ticker="", headline="Test", price_t0=100.0, price_t1=100.0)
    with pytest.raises(ValueError, match="headline must be a non-empty string"):
        BacktestEvent(event_id="EVT_001", event_timestamp="2023-01-01T00:00:00Z", ticker="AAPL", headline="", price_t0=100.0, price_t1=100.0)

def test_invalid_timestamp():
    with pytest.raises(ValueError, match="event_timestamp must be a non-empty string"):
        BacktestEvent(event_id="EVT_001", event_timestamp="", ticker="AAPL", headline="Test", price_t0=100.0, price_t1=100.0)
    with pytest.raises(ValueError, match="event_timestamp must be a valid timestamp"):
        BacktestEvent(event_id="EVT_001", event_timestamp="not_a_time", ticker="AAPL", headline="Test", price_t0=100.0, price_t1=100.0)

def test_invalid_prices():
    # zero/negative
    with pytest.raises(ValueError, match="price_t0 must be finite and strictly positive"):
        BacktestEvent(event_id="EVT_003", event_timestamp="2023-01-01T00:00:00Z", ticker="AAPL", headline="Test", price_t0=0.0, price_t1=100.0)
    with pytest.raises(ValueError, match="price_t1 must be finite and strictly positive"):
        BacktestEvent(event_id="EVT_004", event_timestamp="2023-01-01T00:00:00Z", ticker="AAPL", headline="Test", price_t0=100.0, price_t1=-10.0)

    # NaN
    with pytest.raises(ValueError, match="price_t0 must be finite and strictly positive"):
        BacktestEvent(event_id="EVT_005", event_timestamp="2023-01-01T00:00:00Z", ticker="AAPL", headline="Test", price_t0=float('nan'), price_t1=100.0)

    # Infinity
    with pytest.raises(ValueError, match="price_t1 must be finite and strictly positive"):
        BacktestEvent(event_id="EVT_006", event_timestamp="2023-01-01T00:00:00Z", ticker="AAPL", headline="Test", price_t0=100.0, price_t1=float('inf'))
    with pytest.raises(ValueError, match="price_t1 must be finite and strictly positive"):
        BacktestEvent(event_id="EVT_007", event_timestamp="2023-01-01T00:00:00Z", ticker="AAPL", headline="Test", price_t0=100.0, price_t1=float('-inf'))

def test_signal_return_direction(temp_csv_file):
    # Test specific directional outcomes directly
    tester = HistoricalBacktester(data_path=temp_csv_file)
    events = tester.load_events()

    # EVT_001 MSFT 250 -> 260 (+4.0%)
    forward_return_1 = (events[0].price_t1 - events[0].price_t0) / events[0].price_t0
    assert forward_return_1 == pytest.approx(0.04)

    # EVT_002 AAPL 150 -> 155 (+3.33%)
    forward_return_2 = (events[1].price_t1 - events[1].price_t0) / events[1].price_t0
    assert forward_return_2 == pytest.approx(0.033333333)


# --- MODULE A REPLAY TESTS ---

@patch("src.validation.backtest.RiskEngine")
def test_replay_state_isolation_and_determinism(mock_risk_engine_class, temp_csv_file):
    # Mock Risk Engine to always return a deterministic signal
    mock_engine = MagicMock()
    from src.engine.schemas import RiskSignal
    mock_engine.analyze.return_value = RiskSignal(
        entity="DUMMY", headline="dummy", sentiment_score=1.0,
        event_classification="Earnings & Financials", impact_score=10,
        confidence=1.0, evidence_span="dummy"
    )
    mock_risk_engine_class.return_value = mock_engine

    tester = HistoricalBacktester(data_path=temp_csv_file)
    metrics_run_1 = tester.run_backtest()
    metrics_run_2 = tester.run_backtest()

    # G. Determinism: Running the same events twice produces identical results
    assert metrics_run_1["total_incremental_pnl"] == metrics_run_2["total_incremental_pnl"]

    # E. State isolation:
    # If state leaked, the second event in the CSV would inherit the rebalanced weights
    # from the first event rather than starting from the equal-weight baseline.
    # Since we instantiate a fresh IndexRebalancer per event, they must not leak.
    # We prove this by ensuring determinism holds on repeated full runs (the second run
    # would compound wildly if state leaked across the whole HistoricalBacktester).

@patch("src.validation.backtest.RiskEngine")
def test_replay_portfolio_mathematics(mock_risk_engine_class, temp_csv_file):
    # F. P&L verification & C. Baseline & D. Rebalanced
    mock_engine = MagicMock()
    from src.engine.schemas import RiskSignal

    def fake_analyze(text, entity, **kwargs):
        # Return positive signal for MSFT, negative for AAPL
        score = 1.0 if entity == "MSFT" else -1.0
        return RiskSignal(
            entity=entity, headline=text, sentiment_score=score,
            event_classification="Market Sentiment", impact_score=10,
            confidence=0.9, evidence_span="dummy"
        )
    mock_engine.analyze.side_effect = fake_analyze
    mock_risk_engine_class.return_value = mock_engine

    tester = HistoricalBacktester(data_path=temp_csv_file)
    metrics = tester.run_backtest()
    results = metrics["events_results"]

    assert len(results) == 2
    msft_res = next(r for r in results if r["ticker"] == "MSFT")

    # MSFT event: price_t0 = 250.0, price_t1 = 260.0
    # Baseline: 1,000,000 / 10 = 100,000 per stock at T0.
    # Shares of MSFT = 100,000 / 250 = 400 shares.
    # T1 value of MSFT = 400 * 260 = 104,000.
    # Baseline P&L = +4,000.
    assert msft_res["baseline_pnl"] == pytest.approx(4000.0)

    # Rebalanced MSFT: positive signal -> higher weight than 10%.
    # Therefore rebalanced_pnl should be > 4000.0.
    assert msft_res["rebalanced_pnl"] > 4000.0
    assert msft_res["incremental_pnl"] > 0.0

@patch("src.validation.backtest.RiskEngine")
def test_t0_execution_and_t1_isolation(mock_risk_engine_class, dummy_csv_data):
    # A. T0 execution & B. T1 marking
    mock_engine = MagicMock()
    from src.engine.schemas import RiskSignal
    mock_engine.analyze.return_value = RiskSignal(
        entity="MSFT", headline="dummy", sentiment_score=1.0,
        event_classification="Market Sentiment", impact_score=10,
        confidence=0.9, evidence_span="dummy"
    )
    mock_risk_engine_class.return_value = mock_engine

    # Create two datasets identical except for price_t1
    data_1 = [dict(dummy_csv_data[1])]
    data_1[0]["price_t1"] = "260.0"  # Original +10

    data_2 = [dict(dummy_csv_data[1])]
    data_2[0]["price_t1"] = "300.0"  # Huge +50

    import tempfile, csv, os

    def run_with_data(d):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write("event_id,event_timestamp,ticker,headline,price_t0,price_t1\n")
            writer = csv.DictWriter(f, fieldnames=["event_id", "event_timestamp", "ticker", "headline", "price_t0", "price_t1"])
            writer.writerows(d)
        tester = HistoricalBacktester(data_path=path)
        res = tester.run_backtest()
        os.remove(path)
        return res

    metrics_1 = run_with_data(data_1)
    metrics_2 = run_with_data(data_2)

    # The incremental P&L MUST change because T1 mark-to-market changed
    assert metrics_1["total_incremental_pnl"] != metrics_2["total_incremental_pnl"]

    # The baseline P&L must also change
    assert metrics_1["events_results"][0]["baseline_pnl"] != metrics_2["events_results"][0]["baseline_pnl"]

@patch("src.validation.backtest.RiskEngine")
def test_execution_cost_metrics(mock_risk_engine_class, dummy_csv_data):
    # A. ZERO-TRADE CASE
    mock_engine = MagicMock()
    from src.engine.schemas import RiskSignal

    # Return neutral signal (score 0.0) -> no trade
    mock_engine.analyze.return_value = RiskSignal(
        entity="MSFT", headline="dummy", sentiment_score=0.0,
        event_classification="Market Sentiment", impact_score=0,
        confidence=0.9, evidence_span="dummy"
    )
    mock_risk_engine_class.return_value = mock_engine

    import tempfile, csv, os
    fd, path = tempfile.mkstemp(suffix=".csv")
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        f.write("event_id,event_timestamp,ticker,headline,price_t0,price_t1\n")
        writer = csv.DictWriter(f, fieldnames=["event_id", "event_timestamp", "ticker", "headline", "price_t0", "price_t1"])
        writer.writerows([dummy_csv_data[1]])  # Just MSFT

    tester = HistoricalBacktester(data_path=path)
    metrics = tester.run_backtest()
    res = metrics["events_results"][0]

    assert res["total_abs_trade_value"] == 0.0
    assert res["turnover"] == 0.0
    assert res["turnover_pct"] == 0.0
    assert res["transaction_cost"] == 0.0

    # Now test with a non-zero signal
    mock_engine.analyze.return_value = RiskSignal(
        entity="MSFT", headline="dummy", sentiment_score=1.0,
        event_classification="Market Sentiment", impact_score=10,
        confidence=0.9, evidence_span="dummy"
    )

    tester = HistoricalBacktester(data_path=path)
    metrics = tester.run_backtest()
    res = metrics["events_results"][0]

    # B. TURNOVER MATH
    # C. TRANSACTION COST MATH
    # D. NET P&L MATH
    # E. INCREMENTAL NET P&L

    assert res["total_abs_trade_value"] > 0.0

    # turnover == 0.5 * total_abs_trade_value / initial_capital (which is 1000000)
    expected_turnover = 0.5 * res["total_abs_trade_value"] / 1000000.0
    assert res["turnover"] == pytest.approx(expected_turnover)

    expected_txn_cost = res["total_abs_trade_value"] * tester.txn_cost_rate
    assert res["transaction_cost"] == pytest.approx(expected_txn_cost)

    assert res["net_rebalanced_pnl"] == pytest.approx(res["gross_rebalanced_pnl"] - res["transaction_cost"])
    assert res["incremental_net_pnl"] == pytest.approx(res["incremental_gross_pnl"] - res["transaction_cost"])

    os.remove(path)

@patch("src.validation.backtest.RiskEngine")
def test_t1_isolation_and_cost_rate_sensitivity(mock_risk_engine_class, dummy_csv_data):
    mock_engine = MagicMock()
    from src.engine.schemas import RiskSignal
    mock_engine.analyze.return_value = RiskSignal(
        entity="MSFT", headline="dummy", sentiment_score=1.0,
        event_classification="Market Sentiment", impact_score=10,
        confidence=0.9, evidence_span="dummy"
    )
    mock_risk_engine_class.return_value = mock_engine

    import tempfile, csv, os

    def run_tester(t1_price, txn_cost_rate):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write("event_id,event_timestamp,ticker,headline,price_t0,price_t1\n")
            writer = csv.DictWriter(f, fieldnames=["event_id", "event_timestamp", "ticker", "headline", "price_t0", "price_t1"])
            d = dict(dummy_csv_data[1])
            d["price_t1"] = str(t1_price)
            writer.writerows([d])
        tester = HistoricalBacktester(data_path=path, txn_cost_rate=txn_cost_rate)
        metrics = tester.run_backtest()
        os.remove(path)
        return metrics["events_results"][0]

    # F. T1 ISOLATION
    res_1 = run_tester(260.0, 0.0010)
    res_2 = run_tester(300.0, 0.0010)

    assert res_1["turnover_pct"] == res_2["turnover_pct"]
    assert res_1["transaction_cost"] == res_2["transaction_cost"]
    assert res_1["total_abs_trade_value"] == res_2["total_abs_trade_value"]

    # G. COST-RATE SENSITIVITY
    res_3 = run_tester(260.0, 0.0020)

    # gross P&L is unchanged
    assert res_1["gross_rebalanced_pnl"] == res_3["gross_rebalanced_pnl"]

    # transaction cost changes proportionally
    assert res_3["transaction_cost"] == pytest.approx(res_1["transaction_cost"] * 2.0)

    # net P&L changes accordingly
    assert res_3["net_rebalanced_pnl"] == pytest.approx(res_3["gross_rebalanced_pnl"] - res_3["transaction_cost"])

    # H. DETERMINISM
    res_4 = run_tester(260.0, 0.0010)
    assert res_1["turnover"] == res_4["turnover"]
    assert res_1["transaction_cost"] == res_4["transaction_cost"]
    assert res_1["gross_rebalanced_pnl"] == res_4["gross_rebalanced_pnl"]
