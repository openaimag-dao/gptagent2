from app.database.models import GlobalMarketScore
from app.services.scenarios.engine import compute_scenarios, scenario_threat_level


def _score(**overrides) -> GlobalMarketScore:
    defaults = dict(
        risk_on_score=50,
        risk_off_score=50,
        liquidity_score=50,
        fear_score=50,
        greed_score=50,
        macro_pressure_score=50,
        institutional_activity_score=50,
        crypto_strength_score=50,
        stock_strength_score=50,
        global_score=50,
    )
    defaults.update(overrides)
    return GlobalMarketScore(**defaults)


def test_scenario_probabilities_sum_to_100():
    scenarios = compute_scenarios(_score())
    assert sum(s["probability_pct"] for s in scenarios) == 100


def test_four_named_scenarios_present():
    scenarios = compute_scenarios(_score())
    names = {s["key"] for s in scenarios}
    assert names == {"soft_landing", "risk_off", "liquidity_expansion", "black_swan"}


def test_risk_on_conditions_favor_soft_landing():
    scenarios = compute_scenarios(
        _score(risk_on_score=90, risk_off_score=10, macro_pressure_score=20, greed_score=70)
    )
    by_key = {s["key"]: s["probability_pct"] for s in scenarios}
    assert by_key["soft_landing"] > by_key["risk_off"]
    assert by_key["soft_landing"] > by_key["black_swan"]


def test_stress_conditions_favor_risk_off_over_soft_landing():
    scenarios = compute_scenarios(
        _score(risk_on_score=10, risk_off_score=90, macro_pressure_score=85, fear_score=90)
    )
    by_key = {s["key"]: s["probability_pct"] for s in scenarios}
    assert by_key["risk_off"] > by_key["soft_landing"]


def test_black_swan_is_dampened_even_under_max_stress():
    scenarios = compute_scenarios(
        _score(risk_off_score=100, fear_score=100, macro_pressure_score=100, risk_on_score=0)
    )
    by_key = {s["key"]: s["probability_pct"] for s in scenarios}
    assert by_key["black_swan"] < by_key["risk_off"]


def test_every_probability_is_at_least_the_floor():
    scenarios = compute_scenarios(_score(risk_on_score=0, liquidity_score=0, fear_score=0))
    assert all(s["probability_pct"] >= 1 for s in scenarios)


def test_scenario_threat_level_is_none_without_scenarios():
    assert scenario_threat_level(None) is None
    assert scenario_threat_level([]) is None


def test_scenario_threat_level_is_low_under_calm_conditions():
    scenarios = compute_scenarios(
        _score(risk_on_score=90, risk_off_score=10, macro_pressure_score=10, fear_score=10)
    )
    assert scenario_threat_level(scenarios) == "Low"


def test_scenario_threat_level_is_severe_under_max_stress():
    scenarios = compute_scenarios(
        _score(risk_off_score=100, fear_score=100, macro_pressure_score=100, risk_on_score=0)
    )
    assert scenario_threat_level(scenarios) == "Severe"
