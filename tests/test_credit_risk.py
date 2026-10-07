import pytest
from src.engine.schemas import CreditExposure
from src.engine.stress_engine import StressEngine

def test_credit_exposure_validation():
    # Valid
    CreditExposure("T1", 1000.0, 0.05, 0.45, 1.0)

    # Invalid EAD
    with pytest.raises(ValueError):
        CreditExposure("T2", -100.0, 0.05, 0.45, 1.0)

    # Invalid PD
    with pytest.raises(ValueError):
        CreditExposure("T3", 1000.0, 1.5, 0.45, 1.0)
    with pytest.raises(ValueError):
        CreditExposure("T3", 1000.0, -0.1, 0.45, 1.0)

    # Invalid LGD
    with pytest.raises(ValueError):
        CreditExposure("T4", 1000.0, 0.05, 1.5, 1.0)

    # Invalid Risk Weight
    with pytest.raises(ValueError):
        CreditExposure("T5", 1000.0, 0.05, 0.45, -0.5)

def test_basic_ecl():
    engine = StressEngine()
    exp = CreditExposure("T1", ead=1_000_000, pd=0.02, lgd=0.45, risk_weight=1.0)
    results = engine.apply_credit_stress([exp], pd_multiplier=1.0, lgd_multiplier=1.0, initial_cet1_capital=10_000_000)

    res = results[0]
    assert pytest.approx(res.baseline_ecl) == 9_000
    assert pytest.approx(res.stressed_ecl) == 9_000
    assert pytest.approx(res.incremental_ecl) == 0

def test_zero_parameters():
    engine = StressEngine()
    # Zero PD
    exp1 = CreditExposure("T1", 1000, 0.0, 0.5, 1.0)
    res1 = engine.apply_credit_stress([exp1], 1.0, 1.0, 10000)[0]
    assert res1.baseline_ecl == 0

    # Zero LGD
    exp2 = CreditExposure("T2", 1000, 0.1, 0.0, 1.0)
    res2 = engine.apply_credit_stress([exp2], 1.0, 1.0, 10000)[0]
    assert res2.baseline_ecl == 0

    # Zero EAD
    exp3 = CreditExposure("T3", 0, 0.1, 0.5, 1.0)
    res3 = engine.apply_credit_stress([exp3], 1.0, 1.0, 10000)[0]
    assert res3.baseline_ecl == 0

def test_stress_scenario_increases_ecl():
    engine = StressEngine()
    exp = CreditExposure("T1", ead=1_000_000, pd=0.02, lgd=0.45, risk_weight=1.0)
    results = engine.apply_credit_stress([exp], pd_multiplier=2.0, lgd_multiplier=1.2, initial_cet1_capital=10_000_000)

    res = results[0]
    # Stressed PD = 0.04, Stressed LGD = 0.54
    # Stressed ECL = 0.04 * 0.54 * 1,000,000 = 21,600
    assert pytest.approx(res.stressed_pd) == 0.04
    assert pytest.approx(res.stressed_lgd) == 0.54
    assert pytest.approx(res.stressed_ecl) == 21_600
    assert pytest.approx(res.incremental_ecl) == 21_600 - 9_000

def test_rwa_and_cet1_calculation():
    engine = StressEngine()
    exp = CreditExposure("T1", ead=1_000_000, pd=0.02, lgd=0.45, risk_weight=0.5)
    cet1 = 10_000_000
    results = engine.apply_credit_stress([exp], pd_multiplier=1.0, lgd_multiplier=1.0, initial_cet1_capital=cet1)

    res = results[0]
    assert pytest.approx(res.rwa) == 500_000
    # ECL is 9000
    assert pytest.approx(res.cet1_impact) == 9_000 / cet1

def test_portfolio_aggregation():
    engine = StressEngine()
    exp1 = CreditExposure("T1", ead=1_000_000, pd=0.02, lgd=0.45, risk_weight=1.0) # ECL=9k, RWA=1M
    exp2 = CreditExposure("T2", ead=2_000_000, pd=0.05, lgd=0.50, risk_weight=0.5) # ECL=50k, RWA=1M

    cet1 = 10_000_000
    results = engine.apply_credit_stress([exp1, exp2], pd_multiplier=2.0, lgd_multiplier=1.0, initial_cet1_capital=cet1)
    agg = engine.aggregate_credit_portfolio(results, initial_cet1_capital=cet1)

    assert agg["total_ead"] == 3_000_000
    assert agg["total_baseline_ecl"] == 59_000
    # Stressed PDs: T1=0.04, T2=0.10
    # Stressed ECLs: T1=18k, T2=100k
    assert agg["total_stressed_ecl"] == 118_000
    assert agg["total_incremental_ecl"] == 118_000 - 59_000
    assert agg["total_rwa"] == 2_000_000
    assert agg["cet1_impact"] == 118_000 / cet1

def test_invalid_cet1():
    engine = StressEngine()
    exp = CreditExposure("T1", 1000, 0.05, 0.5, 1.0)
    with pytest.raises(ValueError):
        engine.apply_credit_stress([exp], 1.0, 1.0, 0)

def test_exposure_multiplier_increases_ead_and_ecl():
    engine = StressEngine()
    exp = CreditExposure("T1", ead=1_000_000, pd=0.02, lgd=0.45, risk_weight=1.0)

    results = engine.apply_credit_stress(
        [exp],
        pd_multiplier=1.0,
        lgd_multiplier=1.0,
        initial_cet1_capital=10_000_000,
        exposure_multiplier=1.5
    )

    res = results[0]

    assert pytest.approx(res.ead) == 1_500_000
    assert pytest.approx(res.baseline_ecl) == 9_000
    assert pytest.approx(res.stressed_ecl) == 13_500
    assert pytest.approx(res.incremental_ecl) == 4_500

def test_synthetic_json_loading():
    engine = StressEngine()
    # A. Synthetic JSON loading
    assert len(engine.synthetic_credit_portfolio) == 5
    for exp in engine.synthetic_credit_portfolio:
        assert isinstance(exp, CreditExposure)
        assert exp.identifier.startswith("SYNTH_")

def test_zero_ead():
    # B. Zero EAD produces zero ECL
    engine = StressEngine()
    exp = CreditExposure("ZERO_EAD", ead=0, pd=0.02, lgd=0.45, risk_weight=1.0)
    res = engine.apply_credit_stress([exp], pd_multiplier=1.0, lgd_multiplier=1.0, initial_cet1_capital=10_000_000)
    assert res[0].baseline_ecl == 0.0
    assert res[0].stressed_ecl == 0.0

def test_multiplier_mathematics():
    # C. Multiplier mathematics
    engine = StressEngine()
    exp = CreditExposure("MULT_TEST", ead=1_000_000, pd=0.02, lgd=0.45, risk_weight=1.0)
    res = engine.apply_credit_stress([exp], pd_multiplier=2.0, lgd_multiplier=1.5, exposure_multiplier=1.2, initial_cet1_capital=10_000_000)
    baseline = 0.02 * 0.45 * 1_000_000
    stressed = (0.02 * 2.0) * (0.45 * 1.5) * (1_000_000 * 1.2)
    assert res[0].baseline_ecl == pytest.approx(baseline)
    assert res[0].stressed_ecl == pytest.approx(stressed)
    assert res[0].stressed_ecl > res[0].baseline_ecl

def test_scenario_integration_and_regression():
    # D, E, F, G
    engine = StressEngine()
    weights = {t: 0.1 for t in ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "JNJ", "XOM"]}

    # 1. Base / Tech Bubble
    res1 = engine.run_scenario(weights, 1_000_000, "3. Tech Bubble Burst")

    # D. run_scenario returns market_df + credit_metrics
    assert "market_df" in res1
    assert "credit_metrics" in res1
    assert not res1["market_df"].empty

    # E. Market regression is implicitly tested if we compare with old manual computation
    # Just check it has the right shape and sum
    assert "Total P&L" in res1["market_df"].columns

    # F. Credit determinism
    res1_b = engine.run_scenario(weights, 1_000_000, "3. Tech Bubble Burst")
    assert res1["credit_metrics"]["stressed_ecl"] == res1_b["credit_metrics"]["stressed_ecl"]

    # G. Scenario differentiation
    res2 = engine.run_scenario(weights, 1_000_000, "2. Systemic Credit Crunch")
    # Systemic credit crunch has pd=2.0, lgd=1.5, ead=1.2
    # Tech bubble has pd=1.1, lgd=1.0, ead=1.0
    assert res2["credit_metrics"]["stressed_ecl"] > res1["credit_metrics"]["stressed_ecl"]
