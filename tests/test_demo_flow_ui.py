import pytest

# Obsolete Streamlit test; coverage moved to test_duplicate_bug.py and test_regression_state.py
# from streamlit.testing.v1 import AppTest
# from src.dashboard.app import get_core_systems

def test_demo_flow_comprehensive_obsolete():
    pytest.skip("Test disabled as Streamlit dashboard is obsolete. Covered by test_regression_state.py and test_duplicate_bug.py.")

    # --- Session 1 ---
    at = AppTest.from_file("../src/dashboard/app.py").run(timeout=30)
    assert not at.exception

    # 1. Verify reset button is absent
    assert not any("Restart Demo" in str(getattr(widget, 'label', '')) for widget in at.sidebar.button)

    # 2. Select Offline mode
    at.sidebar.radio[0].set_value("Offline Crisis Replay")
    at = at.run(timeout=30)

    # 3. First offline replay
    at.button[0].click()
    at = at.run(timeout=60)
    assert not at.exception

    # Verify signals generated
    signals_tab = at.tabs[1]
    df = signals_tab.dataframe[0].value
    assert len(df) > 0
    first_run_signals = len(df)

    # 4. Second offline replay in the same session
    at.button[0].click()
    at = at.run(timeout=60)
    assert not at.exception

    # Verify signals generated again (should double because offline run ID bypasses deduplication)
    # The new signals are appended
    df = at.tabs[1].dataframe[0].value
    assert len(df) == first_run_signals * 2

    # --- Session 2 (Fresh UI Session) ---
    at2 = AppTest.from_file("../src/dashboard/app.py").run(timeout=30)
    assert not at2.exception

    # Verify DB still has records (No scan or rerun deletes existing SQLite audit records)
    with db._get_connection() as conn:
        current_records = conn.execute("SELECT COUNT(*) FROM risk_signals").fetchone()[0]
    assert current_records > initial_records

    at2.sidebar.radio[0].set_value("Offline Crisis Replay")
    at2 = at2.run(timeout=30)

    # Verify UI starts clean
    df2 = at2.tabs[1].dataframe[0].value if at2.tabs[1].dataframe else []
    assert len(df2) == 0

    # 5. Offline replay in fresh session
    at2.button[0].click()
    at2 = at2.run(timeout=60)
    assert not at2.exception

    df2_after = at2.tabs[1].dataframe[0].value
    assert len(df2_after) > 0
    assert len(df2_after) == first_run_signals

    # --- Live Feed Deduplication ---
    # Switch to Live
    at2.sidebar.radio[0].set_value("Live Market (Google RSS)")
    at2 = at2.run(timeout=30)

    # Execute scan twice
    at2.button[0].click()
    at2 = at2.run(timeout=60)
    live_df_1 = at2.tabs[1].dataframe[0].value
    live_count = len(live_df_1)

    at2.button[0].click()
    at2 = at2.run(timeout=60)
    live_df_2 = at2.tabs[1].dataframe[0].value
    # Since it's live, deduplication should prevent adding the same articles again immediately
    # Assuming live feed doesn't change in 1 second
    assert len(live_df_2) == live_count

    # Verify empty state message behavior if no new signals were generated
    if len(live_df_2) == live_count:
        # Check if the info message is displayed correctly
        info_msgs = [m.value for m in at2.info]
        assert any("skipped" in msg or "No articles retrieved" in msg for msg in info_msgs)
