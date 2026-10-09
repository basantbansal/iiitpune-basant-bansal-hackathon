import pytest
from src.engine.stress_engine import StressEngine
import math

def test_stress_math_hand_calculation():
    engine = StressEngine()

    # Portfolio: AAPL (60%), NVDA (40%), Total AUM: $1,000,000
    weights = {"AAPL": 0.6, "NVDA": 0.4}
    total_aum = 1_000_000

    # Custom scenario
    engine.scenarios["Test Scenario"] = {
        "equity_shock": -0.10, # -10%
        "rate_shock_bps": 100, # +100 bps
        "spread_shock_bps": 50, # +50 bps
        "desc": "Custom test scenario"
    }

    # AAPL Notional: 600,000
    # AAPL Profile: {"beta": 1.2, "rate_mod_dur": 2.5, "spread_mod_dur": 1.5}
    # AAPL Equity P&L: 600,000 * (1.2 * -0.10) = 600,000 * -0.12 = -72,000
    # AAPL Rate P&L: 600,000 * (-2.5 * 100/10000) = 600,000 * -0.025 = -15,000
    # AAPL Spread P&L: 600,000 * (-1.5 * 50/10000) = 600,000 * -0.0075 = -4,500
    # AAPL Total P&L = -72,000 - 15,000 - 4,500 = -91,500

    # NVDA Notional: 400,000
    # NVDA Profile: {"beta": 2.2, "rate_mod_dur": 4.5, "spread_mod_dur": 2.0}
    # NVDA Equity P&L: 400,000 * (2.2 * -0.10) = 400,000 * -0.22 = -88,000
    # NVDA Rate P&L: 400,000 * (-4.5 * 100/10000) = 400,000 * -0.045 = -18,000
    # NVDA Spread P&L: 400,000 * (-2.0 * 50/10000) = 400,000 * -0.010 = -4,000
    # NVDA Total P&L = -88,000 - 18,000 - 4,000 = -110,000

    # Total P&L = -91,500 - 110,000 = -201,500

    out = engine.run_scenario(weights, total_aum, "Test Scenario")
    df = out["market_df"]

    aapl_row = df[df["Ticker"] == "AAPL"].iloc[0]
    nvda_row = df[df["Ticker"] == "NVDA"].iloc[0]

    assert math.isclose(aapl_row["Equity P&L"], -72000.0)
    assert math.isclose(aapl_row["Rate P&L"], -15000.0)
    assert math.isclose(aapl_row["Spread P&L"], -4500.0)
    assert math.isclose(aapl_row["Total P&L"], -91500.0)

    assert math.isclose(nvda_row["Total P&L"], -110000.0)
    assert math.isclose(df["Total P&L"].sum(), -201500.0)

def test_stress_math_aum_scaling():
    engine = StressEngine()
    weights = {"AAPL": 0.6, "NVDA": 0.4}

    engine.scenarios["Test"] = {
        "equity_shock": -0.10, "rate_shock_bps": 100, "spread_shock_bps": 50
    }

    out_1m = engine.run_scenario(weights, 1_000_000, "Test")["market_df"]
    pnl_1m = out_1m["Total P&L"].sum()
    pct_1m = pnl_1m / 1_000_000

    out_2m = engine.run_scenario(weights, 2_000_000, "Test")["market_df"]
    pnl_2m = out_2m["Total P&L"].sum()
    pct_2m = pnl_2m / 2_000_000

    assert math.isclose(pnl_2m, pnl_1m * 2)
    assert math.isclose(pct_1m, pct_2m)
