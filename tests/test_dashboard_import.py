import pytest
import sys

def test_dashboard_imports_cleanly():
    """
    Verifies that the dashboard can be imported as a proper module 
    without relying on sys.path.append hacks.
    """
    # Temporarily clean any caching
    if "src.dashboard.app" in sys.modules:
        del sys.modules["src.dashboard.app"]
        
    import src.dashboard.app
    assert src.dashboard.app is not None
