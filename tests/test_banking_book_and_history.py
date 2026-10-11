import pytest
import tempfile
import os
import math
from src.stress_testing.stress_engine import StressEngine
from src.storage.db import SignalDatabase

def test_banking_book_math_and_invariants():
    engine = StressEngine()
    
    for sc_name in ["1. 2022 Fed Tightening Shock", "2. Systemic Credit Crunch", "3. Tech Bubble Burst"]:
        res = engine.run_banking_book_stress(sc_name)
        
        assert res["invariant_holds"] is True
        assert math.isclose(
            res["total_post_shock_value"],
            res["total_pre_shock_value"] + res["total_pnl"],
            rel_tol=1e-5,
            abs_tol=0.01
        )
        assert len(res["positions"]) == 14
        assert len(res["by_asset_class"]) == 4
        
        # Verify classes
        class_names = {c["asset_class"] for c in res["by_asset_class"]}
        assert class_names == {
            "Corporate Loans",
            "Fixed Income Bonds",
            "Interest Rate Swaps",
            "Equity Holdings"
        }
        
        # Check that each class satisfies post = pre + pnl
        for ac in res["by_asset_class"]:
            assert math.isclose(
                ac["post_shock_value"],
                ac["pre_shock_value"] + ac["pnl"],
                rel_tol=1e-5,
                abs_tol=0.01
            )

def test_target_weights_history_persistence():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_db_path = os.path.join(tmpdir, "test_history.db")
        db = SignalDatabase(db_path=test_db_path)
        
        weights_1 = {"AAPL": 0.12, "MSFT": 0.08, "NVDA": 0.10}
        scan_time_1 = "2026-10-11T10:00:00Z"
        db.save_target_weights_history(scan_time_1, weights_1)
        
        weights_2 = {"AAPL": 0.14, "MSFT": 0.06, "NVDA": 0.10}
        scan_time_2 = "2026-10-11T11:00:00Z"
        db.save_target_weights_history(scan_time_2, weights_2)
        
        history = db.get_target_weights_history()
        assert len(history) == 6
        
        # Verify scan 1 AAPL
        aapl_1 = [h for h in history if h["scan_time"] == scan_time_1 and h["ticker"] == "AAPL"][0]
        assert aapl_1["target_weight"] == 0.12
        
        # Verify scan 2 AAPL
        aapl_2 = [h for h in history if h["scan_time"] == scan_time_2 and h["ticker"] == "AAPL"][0]
        assert aapl_2["target_weight"] == 0.14

def test_stress_trigger_scenario_mapping():
    from src.api.routes import get_stress_trigger
    from unittest.mock import MagicMock
    import asyncio
    
    # Case 1: No high impact signal
    mock_state = MagicMock()
    mock_state.signals_log = [{"impact_score": 4, "event_classification": "Macroeconomic"}]
    res = asyncio.run(get_stress_trigger(state=mock_state))
    assert res["has_trigger"] is False
    
    # Case 2: High impact Macroeconomic
    mock_state.signals_log = [{"impact_score": 8, "event_classification": "Macroeconomic", "entity": "AAPL", "headline": "Fed hikes rates"}]
    res = asyncio.run(get_stress_trigger(state=mock_state))
    assert res["has_trigger"] is True
    assert res["recommended_scenario"] == "1. 2022 Fed Tightening Shock"
    
    # Case 3: High impact Credit Event
    mock_state.signals_log = [{"impact_score": 7, "event_classification": "Credit Event", "entity": "JPM", "headline": "Bank default risk spreads"}]
    res = asyncio.run(get_stress_trigger(state=mock_state))
    assert res["has_trigger"] is True
    assert res["recommended_scenario"] == "2. Systemic Credit Crunch"
    
    # Case 4: High impact Tech / Product
    mock_state.signals_log = [{"impact_score": 9, "event_classification": "Product Launch", "entity": "NVDA", "headline": "Chip delay crisis"}]
    res = asyncio.run(get_stress_trigger(state=mock_state))
    assert res["has_trigger"] is True
    assert res["recommended_scenario"] == "3. Tech Bubble Burst"
