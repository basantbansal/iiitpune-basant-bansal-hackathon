import pytest
from streamlit.testing.v1 import AppTest

def test_demo_flow_fast():
    at = AppTest.from_file("../src/dashboard/app.py").run(timeout=30)
    assert not at.exception

    # Execute market scan
    at.button[0].click()
    at = at.run(timeout=60)
    assert not at.exception
