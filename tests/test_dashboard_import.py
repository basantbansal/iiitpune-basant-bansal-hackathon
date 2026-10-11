import pytest
import sys

def test_dashboard_imports_cleanly():
    """
    Verifies that the new React+FastAPI backend can be imported as proper modules.
    Replaces the legacy test that imported the retired Streamlit app.
    """
    if "src.api.main" in sys.modules:
        del sys.modules["src.api.main"]
        
    import src.api.main
    import src.api.routes
    assert src.api.main.app is not None
