from unittest.mock import AsyncMock

from app.database.models import (
    Correlation,
    GlobalMarketScore,
    MarketRegimeSnapshot,
    MarketRegimeType,
    ProbabilitySnapshot,
)
from app.services.whatif.engine import WhatIfSimulator


def _global_score(**overrides) -> GlobalMarketScore:
    defaults = dict(
        risk_on_score=50,
        risk_off_score=40,
        liquidity_score=60,
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


def _simulator(
    event_impact_engine=None,
    correlation_engine=None,
    regime_detector=None,
    global_score_engine=None,
    probability_engine=None,
) -> WhatIfSimulator:
    event_impact_engine = event_impact_engine or AsyncMock()
    correlation_engine = correlation_engine or AsyncMock()
    regime_detector = regime_detector or AsyncMock()
    global_score_engine = global_score_engine or AsyncMock()
    probability_engine = probability_engine or AsyncMock()

    regime_detector.get_latest.return_value = MarketRegimeSnapshot(
        regime=MarketRegimeType.ACCUMULATION, inputs={}
    )
    global_score_engine.get_latest.return_value = _global_score()
    probability_engine.get_latest.return_value = ProbabilitySnapshot(
        symbol="BTC", timeframe="1d", prob_up_pct=50.0, prob_down_pct=30.0, prob_flat_pct=20.0
    )

    return WhatIfSimulator(
        event_impact_engine,
        correlation_engine,
        regime_detector,
        global_score_engine,
        probability_engine,
    )


async def test_simulate_returns_none_for_unknown_scenario():
    simulator = _simulator()

    result = await simulator.simulate("not_a_real_scenario")

    assert result is None


async def test_simulate_uses_historical_event_study_when_occurrences_exist():
    event_impact_engine = AsyncMock()

    async def measure_impact(category, symbol, timeframe=None):
        if symbol == "BTC":
            return [{"return_7d_pct": 4.0}, {"return_7d_pct": 6.0}]
        if symbol == "ETH":
            return [{"return_7d_pct": 8.0}]
        return [{"return_7d_pct": None}]

    event_impact_engine.measure_impact.side_effect = measure_impact
    simulator = _simulator(event_impact_engine=event_impact_engine)

    result = await simulator.simulate("fed_cuts_rates")

    assert result["data_source"] == "historical_event_study"
    assert result["impact"]["BTC"]["expected_return_7d_pct"] == 5.0
    assert result["impact"]["BTC"]["sample_size"] == 2
    assert result["impact"]["ETH"]["expected_return_7d_pct"] == 8.0
    assert result["impact"]["SOL"]["expected_return_7d_pct"] is None
    # altcoins proxy averages ETH (8.0) and SOL (None excluded) -> 8.0
    assert result["impact"]["altcoins"]["expected_return_7d_pct"] == 8.0


async def test_simulate_falls_back_to_heuristic_when_no_historical_occurrences():
    event_impact_engine = AsyncMock()
    event_impact_engine.measure_impact.return_value = []
    simulator = _simulator(event_impact_engine=event_impact_engine)

    result = await simulator.simulate("fed_cuts_rates")

    assert result["data_source"] == "heuristic_illustrative"
    assert result["impact"] == {}
    assert result["reasoning"]


async def test_simulate_uses_correlation_direction_when_pair_tracked():
    correlation_engine = AsyncMock()
    correlation_engine.get_latest.return_value = [
        Correlation(
            symbol_a="BTC", symbol_b="DXY", window_days=30, correlation=-0.4, data_points=90
        )
    ]
    simulator = _simulator(correlation_engine=correlation_engine)

    result = await simulator.simulate("dxy_drops")

    assert result["data_source"] == "correlation_direction"
    assert result["impact"]["BTC"]["direction"] == "bullish"
    assert result["impact"]["BTC"]["correlation_30d"] == -0.4
    assert result["impact"]["altcoins"]["direction"] == "bullish"


async def test_simulate_falls_back_to_heuristic_when_correlation_pair_not_tracked():
    correlation_engine = AsyncMock()
    correlation_engine.get_latest.return_value = []
    simulator = _simulator(correlation_engine=correlation_engine)

    result = await simulator.simulate("dxy_drops")

    assert result["data_source"] == "heuristic_illustrative"
    assert result["impact"] == {}


async def test_simulate_scenario_with_no_data_source_is_heuristic():
    simulator = _simulator()

    result = await simulator.simulate("etf_inflows_double")

    assert result["data_source"] == "heuristic_illustrative"
    assert result["impact"] == {}
    assert result["scenario_label"] == "ETF Inflows Double"


async def test_simulate_includes_regime_risk_liquidity_and_probability_context():
    simulator = _simulator()

    result = await simulator.simulate("fed_cuts_rates")

    assert result["current_regime"] == "accumulation"
    assert result["likely_regime_shift_toward"] == "liquidity_expansion"
    assert result["risk_direction"] == "down"
    assert result["liquidity_direction"] == "up"
    assert result["current_risk_off_score"] == 40
    assert result["current_liquidity_score"] == 60
    assert result["current_btc_probability"] == {"up": 50.0, "down": 30.0, "flat": 20.0}


def test_list_scenarios_returns_all_shocks():
    simulator = _simulator()

    scenarios = simulator.list_scenarios()

    assert len(scenarios) == 7
    assert {s["key"] for s in scenarios} == {
        "fed_cuts_rates",
        "etf_inflows_double",
        "dxy_drops",
        "oil_spikes",
        "nasdaq_crashes",
        "btc_loses_support",
        "sol_etf_approved",
    }
