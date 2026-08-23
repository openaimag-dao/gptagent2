import math
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.database.models import AgentForecast, PriceForecastSnapshot
from app.services.analysis.regime import MarketRegime
from app.services.common.statistics import compute_wilson_interval
from app.services.forecast.engine import (
    FORECAST_MODEL_VERSION,
    ForecastEngine,
    _correlation_confidence,
    _distance_from_neutral,
    _onchain_confidence,
    _whale_confidence,
    aggregate_agent_performance,
    check_and_invalidate_forecasts,
    check_target_reached,
    classify_direction_label,
    classify_error_type,
    compute_excursions,
    compute_expected_max_drawdown_pct,
    compute_historical_mean_baseline_error_pct,
    compute_horizon_consistency,
    compute_momentum_score,
    compute_prediction_range,
    compute_price_path,
    compute_price_target,
    compute_probability_distribution,
    compute_scenario_cases,
    derive_learning_insights,
    derive_official_calibration_curve,
    derive_regime_label,
    derive_regime_performance_breakdown,
    derive_risk_meter,
    grade_confidence,
    grade_direction,
    grade_momentum_baseline,
    grade_price_forecasts,
    price_forecast_quality_multiplier,
    summarize_forecast_accuracy,
    summarize_official_performance,
    summarize_official_performance_by_symbol,
)


def test_compute_price_target_applies_empirical_return():
    assert compute_price_target(100.0, 5.0) == 105.0
    assert compute_price_target(100.0, -5.0) == 95.0
    assert compute_price_target(100.0, 0.0) == 100.0


def test_compute_price_path_scales_by_sqrt_of_time():
    path = compute_price_path(100.0, 4.0, fractions=(0.25, 1.0))
    assert path[0]["fraction"] == 0.25
    assert path[0]["change_pct"] == 4.0 * math.sqrt(0.25)
    assert path[1]["change_pct"] == 4.0
    assert path[1]["price"] == 104.0


def test_compute_price_path_default_checkpoints():
    path = compute_price_path(100.0, 4.0)
    assert [p["fraction"] for p in path] == [0.25, 0.5, 0.75, 1.0]
    # Monotonically increasing for a positive mean return.
    prices = [p["price"] for p in path]
    assert prices == sorted(prices)


def test_compute_probability_distribution_empty_without_atr():
    assert compute_probability_distribution(100.0, 2.0, None) == []
    assert compute_probability_distribution(100.0, 2.0, 0.0) == []
    assert compute_probability_distribution(0.0, 2.0, 5.0) == []


def test_compute_probability_distribution_sums_to_roughly_100():
    buckets = compute_probability_distribution(100.0, 0.0, 5.0)
    assert len(buckets) == 4
    total = sum(b["probability_pct"] for b in buckets)
    assert 99.5 <= total <= 100.5


def test_compute_probability_distribution_matches_known_normal_cdf():
    # mean_price = 100 (0% expected return), std = atr = 5.
    # z=1.5 -> Phi(1.5) ~= 0.9332; z=0.5 -> Phi(0.5) ~= 0.6915.
    buckets = compute_probability_distribution(100.0, 0.0, 5.0)
    above = buckets[0]["probability_pct"]
    below = buckets[3]["probability_pct"]
    assert math.isclose(above, (1 - 0.9332) * 100, abs_tol=0.5)
    assert math.isclose(below, 0.3085 * 100, abs_tol=0.5)


def test_compute_prediction_range_none_without_atr():
    assert compute_prediction_range(100.0, 2.0, None) is None
    assert compute_prediction_range(100.0, 2.0, 0.0) is None


def test_compute_prediction_range_uses_15_atr_band():
    range_ = compute_prediction_range(100.0, 0.0, 5.0)
    assert range_ == {"upper_bound": 107.5, "lower_bound": 92.5}


def test_compute_scenario_cases_none_without_atr():
    assert compute_scenario_cases(100.0, 2.0, None, 70, 10, 20, 60.0) is None


def test_compute_scenario_cases_bull_base_bear_targets():
    cases = compute_scenario_cases(100.0, 3.0, 2.0, 70, 10, 20, 60.0)
    assert cases["base_case"]["target_price"] == 103.0
    assert cases["bull_case"]["target_price"] == 105.0
    assert cases["bear_case"]["target_price"] == 101.0
    assert cases["bull_case"]["probability_pct"] == 70
    assert cases["base_case"]["probability_pct"] == 20
    assert cases["bear_case"]["probability_pct"] == 10


def test_compute_scenario_cases_dominant_case_keeps_full_confidence():
    # dominant bucket is bullish (70) -- its confidence should equal
    # effective_confidence_pct exactly, matching today's single forecast.
    cases = compute_scenario_cases(100.0, 3.0, 2.0, 70, 10, 20, 60.0)
    assert cases["bull_case"]["confidence_pct"] == 60
    assert cases["base_case"]["confidence_pct"] < 60
    assert cases["bear_case"]["confidence_pct"] < 60


def test_compute_expected_max_drawdown_pct_none_without_returns():
    assert compute_expected_max_drawdown_pct([]) is None
    assert compute_expected_max_drawdown_pct([None, None]) is None


def test_compute_expected_max_drawdown_pct_reuses_backtest_metric():
    # equity path: 1 -> 1.1 -> 0.99 (peak 1.1, trough 0.99) = 10% drawdown.
    assert compute_expected_max_drawdown_pct([0.1, -0.1]) == 10.0


def test_compute_momentum_score_centers_at_50_when_unavailable():
    assert compute_momentum_score(None) == 50.0


def test_compute_momentum_score_signed():
    assert compute_momentum_score(2.0) == 60.0
    assert compute_momentum_score(-2.0) == 40.0


def test_classify_direction_label_thresholds():
    assert classify_direction_label(80, 10) == "Strong Bullish"
    assert classify_direction_label(50, 30) == "Bullish"
    assert classify_direction_label(10, 80) == "Strong Bearish"
    assert classify_direction_label(30, 50) == "Bearish"
    assert classify_direction_label(40, 40) == "Neutral"


def test_derive_regime_label_high_volatility_overrides_regime():
    assert derive_regime_label(MarketRegime.ACCUMULATION, 70.0, None) == "High Volatility"


def test_derive_regime_label_uses_named_regime():
    assert derive_regime_label(MarketRegime.ACCUMULATION, 30.0, None) == "Accumulation"
    assert derive_regime_label(MarketRegime.DISTRIBUTION, 30.0, None) == "Distribution"
    assert derive_regime_label(MarketRegime.CAPITULATION, 30.0, None) == "Capitulation"
    assert derive_regime_label(MarketRegime.LIQUIDITY_EXPANSION, 30.0, None) == "Expansion"
    assert derive_regime_label(MarketRegime.LIQUIDITY_CONTRACTION, 30.0, None) == "Compression"


def test_derive_regime_label_falls_back_to_trend_or_range():
    assert derive_regime_label(MarketRegime.NEUTRAL, 30.0, 50.0) == "Trending"
    assert derive_regime_label(MarketRegime.NEUTRAL, 10.0, 5.0) == "Compression"
    assert derive_regime_label(MarketRegime.NEUTRAL, 30.0, 5.0) == "Range"
    assert derive_regime_label(None, None, None) == "Range"


def test_derive_risk_meter_extreme_requires_both_high_regime_and_score():
    assert derive_risk_meter(90, MarketRegime.CAPITULATION) == "Extreme"
    assert derive_risk_meter(50, MarketRegime.CAPITULATION) == "High"
    assert derive_risk_meter(None, MarketRegime.CAPITULATION) == "High"
    assert derive_risk_meter(95, MarketRegime.RISK_ON) == "Low"
    assert derive_risk_meter(50, None) == "Unknown"


def test_distance_from_neutral():
    assert _distance_from_neutral(None) is None
    assert _distance_from_neutral(50) == 0
    assert _distance_from_neutral(90) == 80
    assert _distance_from_neutral(10) == 80
    assert _distance_from_neutral(100) == 100


def test_whale_confidence_unavailable_without_data():
    assert _whale_confidence({"available": False}) is None
    assert _whale_confidence({"available": True}) is None


def test_whale_confidence_from_long_short_ratio():
    assert _whale_confidence({"available": True, "long_short_ratio": 1.0}) == 0
    assert _whale_confidence({"available": True, "long_short_ratio": 1.5}) == 100


def test_whale_confidence_from_funding_rate_when_no_ratio():
    assert _whale_confidence({"available": True, "funding_rate": 0.0005}) == 100


def test_onchain_confidence_always_none_today():
    assert _onchain_confidence({"available": False, "metrics": {}}) is None
    assert _onchain_confidence({"available": True, "metrics": {}}) is None


def test_onchain_confidence_activates_honestly_if_ever_available():
    snapshot = {"available": True, "metrics": {"mvrv": 1.2, "sopr": None}}
    assert _onchain_confidence(snapshot) == 50


def test_correlation_confidence_averages_matching_30d_pairs():
    correlations = [
        SimpleNamespace(symbol_a="BTC", symbol_b="NASDAQ", window_days=30, correlation=0.5),
        SimpleNamespace(symbol_a="ETH", symbol_b="BTC", window_days=30, correlation=-0.3),
        SimpleNamespace(symbol_a="BTC", symbol_b="DXY", window_days=7, correlation=0.9),
    ]
    result = _correlation_confidence(correlations, "BTC")
    assert result == round((0.5 + 0.3) / 2 * 100)


def test_correlation_confidence_none_when_no_match():
    assert _correlation_confidence([], "BTC") is None


def _session_factory():
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar = AsyncMock(return_value=None)
    session.scalars = AsyncMock(return_value=[])
    session.__aenter__.return_value = session
    return MagicMock(return_value=session), session


def _build_engine():
    session_factory, session = _session_factory()
    deps = {
        "probability_engine": AsyncMock(),
        "quality_engine": AsyncMock(),
        "technical_engine": AsyncMock(),
        "explanation_engine": AsyncMock(),
        "economic_calendar_engine": AsyncMock(),
        "sentiment_engine": AsyncMock(),
        "correlation_engine": AsyncMock(),
        "whale_engine": AsyncMock(),
        "onchain_engine": AsyncMock(),
        "pattern_engine": AsyncMock(),
    }
    deps["pattern_engine"].get_latest.return_value = []
    engine = ForecastEngine(
        session_factory,
        deps["probability_engine"],
        deps["quality_engine"],
        deps["technical_engine"],
        deps["explanation_engine"],
        deps["economic_calendar_engine"],
        deps["sentiment_engine"],
        deps["correlation_engine"],
        deps["whale_engine"],
        deps["onchain_engine"],
        deps["pattern_engine"],
    )
    return engine, deps, session


# ---- Forecast Intelligence Upgrade: Multi-Horizon Consistency ---------------


def test_compute_horizon_consistency_none_with_fewer_than_2_horizons():
    assert compute_horizon_consistency({}) is None
    assert compute_horizon_consistency({"24h": "Bullish"}) is None


def test_compute_horizon_consistency_ignores_unknown_direction_labels():
    # A horizon with a direction string outside _DIRECTION_SIGN (e.g. a
    # snapshot from before a label taxonomy change) is honestly dropped,
    # not guessed at -- if that leaves fewer than 2 usable horizons the
    # whole result is None.
    assert compute_horizon_consistency({"24h": "Bullish", "3d": "???"}) is None


def test_compute_horizon_consistency_full_agreement():
    directions = {"24h": "Bullish", "3d": "Bullish", "7d": "Strong Bullish", "30d": "Bullish"}
    result = compute_horizon_consistency(directions)
    assert result["short_term"] == "Bullish"
    assert result["medium_term"] == "Bullish"
    assert result["long_term"] == "Bullish"
    assert result["consistency_pct"] == 100.0
    assert result["agreeing_pairs"] == result["total_pairs"] == 6
    assert result["horizons_available"] == ["24h", "30d", "3d", "7d"]


def test_compute_horizon_consistency_short_vs_long_split():
    # Matches the spec's own example: short-term bullish, long-term
    # bearish -- must be reported as a real split, never smoothed away.
    # 3d=Bullish and 7d=Bearish cancel out to a genuinely Neutral medium
    # read (avg sign 0), not just "whichever direction happened first".
    directions = {"24h": "Bullish", "3d": "Bullish", "7d": "Bearish", "30d": "Bearish"}
    result = compute_horizon_consistency(directions)
    assert result["short_term"] == "Bullish"
    assert result["medium_term"] == "Neutral"
    assert result["long_term"] == "Bearish"
    assert 0 < result["consistency_pct"] < 100
    assert "Short-term (24h): Bullish" in result["explanation"]
    assert "Long-term (30d): Bearish" in result["explanation"]


def test_compute_horizon_consistency_partial_horizons_still_computes():
    # Only 2 of the 4 horizons have data yet (e.g. right after a fresh
    # symbol's first forecast cycle) -- must still produce a real,
    # non-fabricated result over just what exists.
    result = compute_horizon_consistency({"24h": "Bearish", "30d": "Bearish"})
    assert result["short_term"] == "Bearish"
    assert result["medium_term"] is None
    assert result["long_term"] == "Bearish"
    assert result["consistency_pct"] == 100.0
    assert result["horizons_available"] == ["24h", "30d"]


def _snapshot(horizon, direction, probability_pct, computed_at):
    return SimpleNamespace(
        horizon=horizon,
        direction=direction,
        probability_pct=probability_pct,
        computed_at=computed_at,
    )


async def test_get_latest_per_horizon_keeps_first_row_seen_per_horizon():
    engine, _, session = _build_engine()
    rows = [
        _snapshot("24h", "Bullish", 68, datetime(2026, 8, 2, tzinfo=UTC)),
        _snapshot("7d", "Neutral", 50, datetime(2026, 8, 1, tzinfo=UTC)),
        # An older 24h row further down the (already-DESC-ordered) result
        # must NOT overwrite the first (newest) one seen above.
        _snapshot("24h", "Bearish", 40, datetime(2026, 7, 30, tzinfo=UTC)),
    ]
    session.scalars = AsyncMock(return_value=rows)
    latest = await engine.get_latest_per_horizon("BTC")
    assert set(latest) == {"24h", "7d"}
    assert latest["24h"].direction == "Bullish"


async def test_get_horizon_consistency_none_without_any_snapshots():
    engine, _, session = _build_engine()
    session.scalars = AsyncMock(return_value=[])
    assert await engine.get_horizon_consistency("BTC") is None


async def test_get_horizon_consistency_none_with_only_one_horizon():
    engine, _, session = _build_engine()
    rows = [_snapshot("24h", "Bullish", 68, datetime(2026, 8, 2, tzinfo=UTC))]
    session.scalars = AsyncMock(return_value=rows)
    assert await engine.get_horizon_consistency("BTC") is None


async def test_get_horizon_consistency_includes_by_horizon_detail():
    engine, _, session = _build_engine()
    rows = [
        _snapshot("24h", "Bullish", 68, datetime(2026, 8, 2, tzinfo=UTC)),
        _snapshot("30d", "Bearish", 64, datetime(2026, 8, 1, tzinfo=UTC)),
    ]
    session.scalars = AsyncMock(return_value=rows)
    result = await engine.get_horizon_consistency("BTC")
    assert result["short_term"] == "Bullish"
    assert result["long_term"] == "Bearish"
    assert result["by_horizon"]["24h"]["probability_pct"] == 68
    assert result["by_horizon"]["30d"]["direction"] == "Bearish"


async def test_compute_returns_none_for_unknown_horizon():
    engine, _, _ = _build_engine()
    assert await engine.compute("BTC", "99h") is None


async def test_compute_returns_none_for_unknown_symbol():
    engine, _, _ = _build_engine()
    assert await engine.compute("NOT_A_SYMBOL", "24h") is None


async def test_compute_returns_none_without_history():
    engine, _, _ = _build_engine()
    with patch("app.services.forecast.engine.get_series", AsyncMock(return_value=[])):
        assert await engine.compute("BTC", "24h") is None


async def test_compute_returns_none_without_probability_snapshot():
    engine, deps, _ = _build_engine()
    history_row = SimpleNamespace(close=100.0, atr=2.0)
    deps["probability_engine"].compute_and_store.return_value = None
    with patch("app.services.forecast.engine.get_series", AsyncMock(return_value=[history_row])):
        assert await engine.compute("BTC", "24h") is None


async def test_compute_pins_price_to_probability_reference_timestamp_not_latest_row():
    """Regression test for the get_series() race between this engine's own
    fetch and ProbabilityEngine.compute_and_store's independent internal
    fetch: if a newer bar has landed by the time this engine's own fetch
    runs, current_price/atr must still come from the exact bar the
    probability was computed from, not whatever is now the newest row."""
    engine, deps, _ = _build_engine()
    older_row = SimpleNamespace(
        close=100.0, atr=2.0, timestamp=datetime(2026, 8, 1, tzinfo=UTC), return_pct=0.01
    )
    newer_row = SimpleNamespace(
        close=999.0, atr=99.0, timestamp=datetime(2026, 8, 2, tzinfo=UTC), return_pct=0.02
    )
    deps["probability_engine"].compute_and_store.return_value = SimpleNamespace(
        prob_up_pct=70,
        prob_down_pct=10,
        prob_flat_pct=20,
        sample_size=50,
        avg_forward_return_pct=3.0,
        reference_timestamp=older_row.timestamp,
    )
    deps["quality_engine"].evaluate.return_value = None
    deps["technical_engine"].get_latest.return_value = None
    deps["explanation_engine"].build.return_value = {}
    deps["economic_calendar_engine"].get_upcoming.return_value = []
    deps["sentiment_engine"].get_latest.return_value = None
    deps["correlation_engine"].get_latest.return_value = []
    deps["whale_engine"].get_snapshot.return_value = {"available": False}
    deps["onchain_engine"].get_snapshot.return_value = {"available": False, "metrics": {}}

    with patch(
        "app.services.forecast.engine.get_series",
        AsyncMock(return_value=[older_row, newer_row]),
    ):
        payload = await engine.compute("BTC", "24h")

    assert payload["current_price"] == 100.0
    assert payload["reference_timestamp"] == older_row.timestamp.isoformat()


async def test_compute_builds_full_payload_and_persists():
    engine, deps, session = _build_engine()
    history_row = SimpleNamespace(
        close=100.0, atr=2.0, timestamp=datetime(2026, 8, 2, tzinfo=UTC), return_pct=0.01
    )
    probability_snapshot = SimpleNamespace(
        prob_up_pct=70,
        prob_down_pct=10,
        prob_flat_pct=20,
        sample_size=50,
        avg_forward_return_pct=3.0,
        reference_timestamp=history_row.timestamp,
    )
    deps["probability_engine"].compute_and_store.return_value = probability_snapshot
    deps["quality_engine"].evaluate.return_value = None
    deps["technical_engine"].get_latest.return_value = SimpleNamespace(
        confidence=80.0, trend_strength=45.0, support=95.0, resistance=105.0, momentum=1.5
    )
    deps["explanation_engine"].build.return_value = {"indicators": [{"name": "rsi", "points": 2}]}
    deps["economic_calendar_engine"].get_upcoming.return_value = []
    deps["sentiment_engine"].get_latest.return_value = SimpleNamespace(
        news_sentiment_score=70, global_sentiment_score=65
    )
    deps["correlation_engine"].get_latest.return_value = []
    deps["whale_engine"].get_snapshot.return_value = {"available": False}
    deps["onchain_engine"].get_snapshot.return_value = {"available": False, "metrics": {}}
    deps["pattern_engine"].get_latest.return_value = [
        SimpleNamespace(
            pattern_name="golden_cross",
            direction="bullish",
            timestamp=datetime(2026, 8, 1, tzinfo=UTC),
        )
    ]

    with patch("app.services.forecast.engine.get_series", AsyncMock(return_value=[history_row])):
        payload = await engine.compute("BTC", "24h")

    assert payload is not None
    assert payload["symbol"] == "BTC"
    assert payload["current_price"] == 100.0
    assert payload["target_price"] == 103.0
    assert payload["direction"] == "Strong Bullish"
    assert payload["probability_pct"] == 70
    assert len(payload["price_path"]) == 4
    assert len(payload["probability_distribution"]) == 4
    assert payload["key_levels"]["support_1"] == 95.0
    assert payload["key_levels"]["resistance_1"] == 105.0
    assert payload["confidence_breakdown"][0]["name"] == "Technical Analysis"
    assert payload["confidence_breakdown"][0]["confidence_pct"] == 80
    breakdown = {r["name"]: r["confidence_pct"] for r in payload["confidence_breakdown"]}
    assert "Momentum" in breakdown
    assert "Pattern" in breakdown
    assert breakdown["Pattern"] == 100  # single unanimous bullish signal
    assert "Risk" in breakdown
    assert breakdown["Risk"] is None  # no watchdog snapshot in this test
    assert payload["reference_timestamp"] == history_row.timestamp.isoformat()
    assert payload["prediction_range"] == {"upper_bound": 106.0, "lower_bound": 100.0}
    assert payload["scenario_cases"]["bull_case"]["target_price"] == 105.0
    assert payload["scenario_cases"]["base_case"]["target_price"] == 103.0
    assert payload["scenario_cases"]["bear_case"]["target_price"] == 101.0
    assert payload["scenario_cases"]["bull_case"]["probability_pct"] == 70
    assert payload["scenario_cases"]["base_case"]["probability_pct"] == 20
    assert payload["scenario_cases"]["bear_case"]["probability_pct"] == 10
    assert payload["expected_max_drawdown_pct"] == 0.0
    assert payload["momentum_score"] is not None
    assert payload["track_record"] == {
        "evaluated_count": 0,
        "avg_abs_error_pct": None,
        "win_rate_pct": None,
        "win_rate_sample_size": 0,
        "quality_multiplier": None,
        "adjusted_confidence_pct": None,
    }
    # One PriceForecastSnapshot row plus one AgentForecast row per
    # confidence_breakdown entry (Forecasting 2.0 Part 10/11's per-agent
    # evidence table) -- confidence_breakdown has 10 rows (Technical/News/
    # Sentiment/Macro/Whales/On-chain/Correlations/Momentum/Pattern/Risk).
    assert session.add.call_count == 1 + len(payload["confidence_breakdown"])
    added_snapshot = session.add.call_args_list[0][0][0]
    assert isinstance(added_snapshot, PriceForecastSnapshot)
    added_agent_rows = [c[0][0] for c in session.add.call_args_list[1:]]
    assert all(isinstance(r, AgentForecast) for r in added_agent_rows)
    assert {r.agent_name for r in added_agent_rows} == {
        r["name"] for r in payload["confidence_breakdown"]
    }
    session.commit.assert_awaited()


async def test_confidence_breakdown_risk_row_reuses_watchdog_risk_score():
    engine, deps, _ = _build_engine()
    deps["sentiment_engine"].get_latest.return_value = None
    deps["correlation_engine"].get_latest.return_value = []
    deps["whale_engine"].get_snapshot.return_value = {"available": False}
    deps["onchain_engine"].get_snapshot.return_value = {"available": False, "metrics": {}}
    deps["pattern_engine"].get_latest.return_value = []
    watchdog = SimpleNamespace(confidence_score=None, risk_score=80)

    rows = await engine._confidence_breakdown("BTC", None, watchdog, momentum_score=None)

    breakdown = {r.name: r.confidence_pct for r in rows}
    # risk_score=80 is 30 points from the neutral center (50) -> distance*2 = 60
    assert breakdown["Risk"] == 60
    assert breakdown["Momentum"] is None  # no momentum_score given -> honestly unavailable
    assert breakdown["Pattern"] is None  # no patterns detected


def test_price_forecast_quality_multiplier_none_without_enough_track_record():
    assert price_forecast_quality_multiplier(None, None, 1.0) is None
    assert price_forecast_quality_multiplier(0.5, None, 1.0) is None
    assert price_forecast_quality_multiplier(0.5, 5, 1.0) is None
    assert price_forecast_quality_multiplier(0.5, 20, None) is None
    assert price_forecast_quality_multiplier(0.5, 20, 0.0) is None


def test_price_forecast_quality_multiplier_perfect_accuracy_is_one():
    assert price_forecast_quality_multiplier(0.0, 20, 1.0) == 1.0


def test_price_forecast_quality_multiplier_at_or_beyond_volatility_band_is_zero():
    assert price_forecast_quality_multiplier(1.0, 20, 1.0) == 0.0
    assert price_forecast_quality_multiplier(2.0, 20, 1.0) == 0.0


def test_price_forecast_quality_multiplier_scales_between_extremes():
    multiplier = price_forecast_quality_multiplier(0.5, 20, 1.0)
    assert multiplier == 0.5


def _forecast_session(scalars_return, get_return=None):
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=scalars_return)
    session.get = AsyncMock(return_value=get_return)
    session.commit = AsyncMock()
    session.__aenter__.return_value = session
    return MagicMock(return_value=session), session


async def test_grade_price_forecasts_returns_zero_without_ungraded_rows():
    session_factory, session = _forecast_session([])
    with patch("app.services.forecast.engine.get_series", AsyncMock()) as mock_get_series:
        graded = await grade_price_forecasts(session_factory, "BTC", object())
    assert graded == 0
    mock_get_series.assert_not_called()


async def test_grade_price_forecasts_skips_a_horizon_that_hasnt_elapsed_yet():
    ts0 = datetime(2026, 8, 1, tzinfo=UTC)
    rows = [SimpleNamespace(timestamp=ts0, close=100.0, return_pct=None)]
    ungraded = SimpleNamespace(id=1, reference_timestamp=ts0, horizon="24h", target_price=103.0)
    db_row = SimpleNamespace(realized_price=None, error_pct=None, evaluated_at=None)
    session_factory, session = _forecast_session([ungraded], db_row)

    with patch("app.services.forecast.engine.get_series", AsyncMock(return_value=rows)):
        graded = await grade_price_forecasts(session_factory, "BTC", object())

    assert graded == 0
    assert db_row.realized_price is None
    session.get.assert_not_awaited()


def test_grade_direction_bullish_correct():
    assert grade_direction("Bullish", 100.0, 105.0) is True


def test_grade_direction_bullish_wrong():
    assert grade_direction("Strong Bullish", 100.0, 95.0) is False


def test_grade_direction_bearish_correct():
    assert grade_direction("Bearish", 100.0, 95.0) is True


def test_grade_direction_neutral_is_honestly_ungraded():
    assert grade_direction("Neutral", 100.0, 105.0) is None


def test_grade_direction_unchanged_price_fails_directional_call():
    assert grade_direction("Bullish", 100.0, 100.0) is False


def test_grade_confidence_within_volatility_band():
    assert grade_confidence(1.5, 2.0) is True


def test_grade_confidence_beyond_volatility_band():
    assert grade_confidence(3.5, 2.0) is False


def test_grade_confidence_none_without_volatility_band():
    assert grade_confidence(1.0, None) is None
    assert grade_confidence(1.0, 0) is None


# ---- POST-V9 Phase 14: baseline challenge pure functions --------------------


def test_grade_momentum_baseline_none_without_prior_return():
    assert grade_momentum_baseline(None, 100.0, 105.0) is None


def test_grade_momentum_baseline_none_when_prior_return_flat():
    assert grade_momentum_baseline(0.0, 100.0, 105.0) is None


def test_grade_momentum_baseline_correct_when_up_move_continues():
    assert grade_momentum_baseline(0.02, 100.0, 105.0) is True


def test_grade_momentum_baseline_incorrect_when_up_move_reverses():
    assert grade_momentum_baseline(0.02, 100.0, 95.0) is False


def test_grade_momentum_baseline_correct_when_down_move_continues():
    assert grade_momentum_baseline(-0.02, 100.0, 95.0) is True


def test_grade_momentum_baseline_incorrect_when_down_move_reverses():
    assert grade_momentum_baseline(-0.02, 100.0, 105.0) is False


def test_compute_historical_mean_baseline_error_pct_none_without_baseline():
    assert compute_historical_mean_baseline_error_pct(None, 100.0, 105.0) is None


def test_compute_historical_mean_baseline_error_pct_exact_match_is_zero():
    # naive target = 100 * (1 + 5.0/100) = 105.0, exactly matches realized
    assert compute_historical_mean_baseline_error_pct(5.0, 100.0, 105.0) == 0.0


def test_compute_historical_mean_baseline_error_pct_computes_signed_error():
    # naive target = 100 * (1 + 2.0/100) = 102.0, realized = 105.0
    # error = 100 * (105.0 - 102.0) / 102.0
    assert compute_historical_mean_baseline_error_pct(2.0, 100.0, 105.0) == round(
        100 * (105.0 - 102.0) / 102.0, 4
    )


# ---- Forecast Intelligence Upgrade: target_reached (intrabar touch) --------


def test_check_target_reached_none_for_neutral_call():
    window = [SimpleNamespace(high=110.0, low=95.0)]
    assert check_target_reached("Neutral", 100.0, 103.0, window) is None


def test_check_target_reached_none_when_target_equals_current_price():
    window = [SimpleNamespace(high=110.0, low=95.0)]
    assert check_target_reached("Bullish", 100.0, 100.0, window) is None


def test_check_target_reached_true_when_high_touches_a_bullish_target():
    window = [SimpleNamespace(high=101.0, low=99.0), SimpleNamespace(high=104.0, low=100.0)]
    assert check_target_reached("Bullish", 100.0, 103.0, window) is True


def test_check_target_reached_false_when_high_never_reaches_a_bullish_target():
    window = [SimpleNamespace(high=101.0, low=99.0), SimpleNamespace(high=102.0, low=98.0)]
    assert check_target_reached("Bullish", 100.0, 103.0, window) is False


def test_check_target_reached_true_when_low_touches_a_bearish_target():
    window = [SimpleNamespace(high=100.0, low=98.0), SimpleNamespace(high=99.0, low=96.0)]
    assert check_target_reached("Bearish", 100.0, 97.0, window) is True


def test_check_target_reached_false_when_low_never_reaches_a_bearish_target():
    window = [SimpleNamespace(high=100.0, low=98.0)]
    assert check_target_reached("Bearish", 100.0, 97.0, window) is False


def test_check_target_reached_false_over_an_empty_window():
    # Horizon just elapsed with no intervening bars -- honestly False
    # (never touched), not None, since the direction/target claim is
    # real and gradable, there just happened to be nothing between.
    assert check_target_reached("Bullish", 100.0, 103.0, []) is False


# ---- Forecasting 2.0: MAE/MFE path analysis + error classification --------


def test_compute_excursions_none_for_neutral_call():
    window = [SimpleNamespace(high=110.0, low=95.0)]
    assert compute_excursions("Neutral", 100.0, window) == (None, None)


def test_compute_excursions_none_for_empty_window():
    assert compute_excursions("Bullish", 100.0, []) == (None, None)


def test_compute_excursions_bullish_mfe_is_the_high_mae_is_the_low():
    # Ran up to 107 (favorable, +7%) then down to 96 (adverse, -4%).
    window = [SimpleNamespace(high=107.0, low=101.0), SimpleNamespace(high=103.0, low=96.0)]
    mfe, mae = compute_excursions("Bullish", 100.0, window)
    assert mfe == 7.0
    assert mae == -4.0


def test_compute_excursions_bearish_mfe_is_negative_mae_is_positive():
    # A "down" call's favorable excursion is itself negative (price fell,
    # as the call implied) -- same signed convention as
    # AlertPerformanceGrade's own max_favorable/adverse_excursion_pct.
    window = [SimpleNamespace(high=107.0, low=101.0), SimpleNamespace(high=103.0, low=93.0)]
    mfe, mae = compute_excursions("Bearish", 100.0, window)
    assert mfe == -7.0
    assert mae == 7.0


def test_classify_error_type_none_when_direction_correct_or_ungraded():
    assert classify_error_type(True, False, True) is None
    assert classify_error_type(None, None, None) is None


def test_classify_error_type_timing_error_when_target_was_touched():
    assert classify_error_type(False, True, True) == "TIMING_ERROR"


def test_classify_error_type_volatility_error_when_confidence_band_missed():
    assert classify_error_type(False, False, False) == "VOLATILITY_ERROR"


def test_classify_error_type_direction_error_as_the_default_miss():
    assert classify_error_type(False, False, True) == "DIRECTION_ERROR"


async def test_grade_price_forecasts_grades_an_elapsed_row():
    ts0 = datetime(2026, 8, 1, tzinfo=UTC)
    rows = [
        SimpleNamespace(timestamp=ts0, close=100.0, atr=2.0, return_pct=None),
        SimpleNamespace(
            timestamp=ts0 + timedelta(days=1),
            close=105.0,
            high=105.0,
            low=105.0,
            atr=2.0,
            return_pct=0.05,
        ),
    ]
    ungraded = SimpleNamespace(
        id=1,
        reference_timestamp=ts0,
        horizon="24h",
        target_price=103.0,
        current_price=100.0,
        direction="Bullish",
    )
    db_row = SimpleNamespace(
        realized_price=None,
        error_pct=None,
        direction_correct=None,
        confidence_correct=None,
        evaluated_at=None,
        forecast_status="ACTIVE",
    )
    session_factory, session = _forecast_session([ungraded], db_row)

    with patch("app.services.forecast.engine.get_series", AsyncMock(return_value=rows)):
        graded = await grade_price_forecasts(session_factory, "BTC", object())

    assert graded == 1
    assert db_row.realized_price == 105.0
    assert db_row.error_pct == round(100 * (105.0 - 103.0) / 103.0, 4)
    assert db_row.direction_correct is True  # predicted Bullish, realized 105 > 100 current_price
    assert db_row.confidence_correct is not None
    assert db_row.evaluated_at is not None
    # POST-V9 Phase 17: a still-ACTIVE forecast transitions to GRADED once graded.
    assert db_row.forecast_status == "GRADED"
    # POST-V9 Phase 14: the very first row in history has no prior period
    # and no prior baseline sample -- honestly None, not fabricated.
    assert db_row.momentum_baseline_correct is None
    assert db_row.historical_mean_baseline_error_pct is None
    # Forecast Intelligence Upgrade: price actually touched the target
    # (high 105.0 >= target 103.0) during the window, not just ended up
    # past it at horizon-elapse.
    assert db_row.target_reached is True
    session.commit.assert_awaited()


async def test_grade_price_forecasts_computes_baseline_comparisons():
    ts0 = datetime(2026, 8, 1, tzinfo=UTC)
    rows = [
        SimpleNamespace(timestamp=ts0 - timedelta(days=2), close=95.0, atr=2.0, return_pct=0.02),
        SimpleNamespace(timestamp=ts0 - timedelta(days=1), close=100.0, atr=2.0, return_pct=0.05),
        SimpleNamespace(timestamp=ts0, close=100.0, atr=2.0, return_pct=None),
        SimpleNamespace(
            timestamp=ts0 + timedelta(days=1),
            close=105.0,
            high=105.0,
            low=105.0,
            atr=2.0,
            return_pct=0.05,
        ),
    ]
    ungraded = SimpleNamespace(
        id=1,
        reference_timestamp=ts0,
        horizon="24h",
        target_price=103.0,
        current_price=100.0,
        direction="Bullish",
    )
    db_row = SimpleNamespace(
        realized_price=None,
        error_pct=None,
        direction_correct=None,
        confidence_correct=None,
        evaluated_at=None,
        forecast_status="ACTIVE",
    )
    session_factory, session = _forecast_session([ungraded], db_row)

    with patch("app.services.forecast.engine.get_series", AsyncMock(return_value=rows)):
        graded = await grade_price_forecasts(session_factory, "BTC", object())

    assert graded == 1
    # prior period (idx=1) had +5% -> naive momentum predicts "up";
    # realized_price 105 > current_price 100 -> up actually happened -> correct
    assert db_row.momentum_baseline_correct is True
    # the one prior forward-return window knowable at reference time (idx=0
    # -> idx=1, +5%) gives a 5.0% historical-mean baseline -> naive target
    # 100*(1.05)=105.0, exactly matching the real realized_price of 105.0
    assert db_row.historical_mean_baseline_error_pct == 0.0


async def test_grade_price_forecasts_preserves_invalidated_status():
    ts0 = datetime(2026, 8, 1, tzinfo=UTC)
    rows = [
        SimpleNamespace(timestamp=ts0, close=100.0, atr=2.0, return_pct=None),
        SimpleNamespace(
            timestamp=ts0 + timedelta(days=1),
            close=105.0,
            high=105.0,
            low=105.0,
            atr=2.0,
            return_pct=0.05,
        ),
    ]
    ungraded = SimpleNamespace(
        id=1,
        reference_timestamp=ts0,
        horizon="24h",
        target_price=103.0,
        current_price=100.0,
        direction="Bullish",
    )
    db_row = SimpleNamespace(
        realized_price=None,
        error_pct=None,
        direction_correct=None,
        confidence_correct=None,
        evaluated_at=None,
        forecast_status="INVALIDATED",
    )
    session_factory, session = _forecast_session([ungraded], db_row)

    with patch("app.services.forecast.engine.get_series", AsyncMock(return_value=rows)):
        graded = await grade_price_forecasts(session_factory, "BTC", object())

    assert graded == 1
    # grading fills in the outcome fields but never erases an existing
    # INVALIDATED marker by resetting it to a generic graded status
    assert db_row.forecast_status == "INVALIDATED"
    assert db_row.evaluated_at is not None


async def test_grade_price_forecasts_skips_an_unmatched_reference_timestamp():
    rows = [
        SimpleNamespace(timestamp=datetime(2026, 8, 1, tzinfo=UTC), close=100.0, return_pct=None)
    ]
    ungraded = SimpleNamespace(
        id=1,
        reference_timestamp=datetime(2020, 1, 1, tzinfo=UTC),
        horizon="24h",
        target_price=103.0,
    )
    session_factory, session = _forecast_session([ungraded])

    with patch("app.services.forecast.engine.get_series", AsyncMock(return_value=rows)):
        graded = await grade_price_forecasts(session_factory, "BTC", object())

    assert graded == 0
    session.get.assert_not_awaited()


async def test_summarize_forecast_accuracy_none_without_graded_rows():
    session_factory, _ = _forecast_session([])
    assert await summarize_forecast_accuracy(session_factory, "BTC", "24h") is None


async def test_summarize_forecast_accuracy_averages_absolute_error():
    graded_rows = [
        SimpleNamespace(error_pct=1.0, direction_correct=True),
        SimpleNamespace(error_pct=-3.0, direction_correct=False),
    ]
    session_factory, _ = _forecast_session(graded_rows)
    summary = await summarize_forecast_accuracy(session_factory, "BTC", "24h")
    assert summary == {
        "evaluated_count": 2,
        "avg_abs_error_pct": 2.0,
        "win_rate_pct": 50.0,
        "win_rate_sample_size": 2,
    }


# Win Rate (accuracy increment, per user request "чтобы мне посмотреть
# прогноза винрейт"): direction_correct-based rate over this symbol/
# horizon's own graded forecasts, same convention summarize_official_
# performance already uses -- a Neutral call (direction_correct=None)
# has no direction to grade, so it's excluded from both the numerator
# and the denominator rather than counted as a loss.
async def test_summarize_forecast_accuracy_win_rate_excludes_neutral_calls():
    graded_rows = [
        SimpleNamespace(error_pct=1.0, direction_correct=True),
        SimpleNamespace(error_pct=2.0, direction_correct=True),
        SimpleNamespace(error_pct=3.0, direction_correct=False),
        SimpleNamespace(error_pct=0.5, direction_correct=None),  # Neutral call
    ]
    session_factory, _ = _forecast_session(graded_rows)
    summary = await summarize_forecast_accuracy(session_factory, "BTC", "24h")
    assert summary["win_rate_pct"] == pytest.approx(66.7)
    assert summary["win_rate_sample_size"] == 3


async def test_summarize_forecast_accuracy_win_rate_none_when_all_neutral():
    graded_rows = [SimpleNamespace(error_pct=1.0, direction_correct=None)]
    session_factory, _ = _forecast_session(graded_rows)
    summary = await summarize_forecast_accuracy(session_factory, "BTC", "24h")
    assert summary["win_rate_pct"] is None
    assert summary["win_rate_sample_size"] == 0


def _invalidation_session(active_rows, regime_row, db_row=None):
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=active_rows)
    session.scalar = AsyncMock(return_value=regime_row)
    session.get = AsyncMock(return_value=db_row)
    session.commit = AsyncMock()
    session.__aenter__.return_value = session
    return MagicMock(return_value=session), session


async def test_check_and_invalidate_forecasts_returns_zero_without_active_rows():
    session_factory, _ = _invalidation_session([], regime_row=None)
    with patch("app.services.forecast.engine.get_series", AsyncMock()) as mock_get_series:
        invalidated = await check_and_invalidate_forecasts(session_factory, "BTC", object())
    assert invalidated == 0
    mock_get_series.assert_not_called()


async def test_check_and_invalidate_forecasts_invalidates_on_price_breach():
    active = SimpleNamespace(
        id=1,
        direction="Bullish",
        key_levels={"invalidation_level": 95.0},
        regime_at_forecast="bull",
    )
    db_row = SimpleNamespace(
        forecast_status="ACTIVE", invalidation_reason=None, invalidated_at=None
    )
    regime_row = SimpleNamespace(regime=SimpleNamespace(value="bull"))
    session_factory, session = _invalidation_session([active], regime_row, db_row)
    rows = [SimpleNamespace(close=90.0)]  # breaches the 95.0 invalidation_level

    with patch("app.services.forecast.engine.get_series", AsyncMock(return_value=rows)):
        invalidated = await check_and_invalidate_forecasts(session_factory, "BTC", object())

    assert invalidated == 1
    assert db_row.forecast_status == "INVALIDATED"
    assert db_row.invalidation_reason is not None
    assert db_row.invalidated_at is not None
    session.get.assert_awaited_once()


async def test_check_and_invalidate_forecasts_stays_active_when_nothing_triggers():
    active = SimpleNamespace(
        id=1,
        direction="Bullish",
        key_levels={"invalidation_level": 95.0},
        regime_at_forecast="bull",
    )
    regime_row = SimpleNamespace(regime=SimpleNamespace(value="bull"))
    session_factory, session = _invalidation_session([active], regime_row)
    rows = [SimpleNamespace(close=100.0)]  # well above the invalidation_level, regime unchanged

    with patch("app.services.forecast.engine.get_series", AsyncMock(return_value=rows)):
        invalidated = await check_and_invalidate_forecasts(session_factory, "BTC", object())

    assert invalidated == 0
    session.get.assert_not_awaited()


async def test_check_and_invalidate_forecasts_invalidates_on_regime_change():
    active = SimpleNamespace(
        id=1,
        direction="Bullish",
        key_levels={"invalidation_level": 95.0},
        regime_at_forecast="bull",
    )
    db_row = SimpleNamespace(
        forecast_status="ACTIVE", invalidation_reason=None, invalidated_at=None
    )
    regime_row = SimpleNamespace(regime=SimpleNamespace(value="bear"))
    session_factory, session = _invalidation_session([active], regime_row, db_row)
    rows = [SimpleNamespace(close=100.0)]  # price fine, but regime flipped

    with patch("app.services.forecast.engine.get_series", AsyncMock(return_value=rows)):
        invalidated = await check_and_invalidate_forecasts(session_factory, "BTC", object())

    assert invalidated == 1
    assert "Regime changed" in db_row.invalidation_reason


async def test_persist_assigns_incrementing_forecast_version():
    engine, deps, session = _build_engine()
    session.scalar = AsyncMock(return_value=3)  # prior_version already at 3

    payload = {
        "symbol": "BTC",
        "horizon": "24h",
        "current_price": 100.0,
        "target_price": 103.0,
        "expected_change_pct": 3.0,
        "direction": "Bullish",
        "probability_pct": 70,
        "price_path": [],
        "probability_distribution": [],
        "key_levels": {},
    }
    version = await engine._persist(
        payload,
        datetime(2026, 8, 2, tzinfo=UTC),
        "high",
        regime_at_forecast="bull",
        is_official_daily=False,
        confidence_breakdown=[],
    )

    assert version == 4
    added = session.add.call_args[0][0]
    assert added.forecast_version == 4
    assert added.regime_at_forecast == "bull"


async def test_persist_starts_at_version_one_when_no_prior_forecast():
    engine, deps, session = _build_engine()
    session.scalar = AsyncMock(return_value=None)

    payload = {
        "symbol": "ETH",
        "horizon": "7d",
        "current_price": 50.0,
        "target_price": 52.0,
        "expected_change_pct": 4.0,
        "direction": "Neutral",
        "probability_pct": 50,
        "price_path": [],
        "probability_distribution": [],
        "key_levels": {},
    }
    version = await engine._persist(
        payload,
        datetime(2026, 8, 2, tzinfo=UTC),
        "low",
        regime_at_forecast=None,
        is_official_daily=False,
        confidence_breakdown=[],
    )

    assert version == 1


async def test_persist_supersedes_prior_active_forecasts_for_same_symbol_horizon():
    # POST-V9 Phase 17: at most one ACTIVE forecast per (symbol, horizon)
    # at a time -- a prior ACTIVE row must be marked SUPERSEDED, not left
    # ACTIVE alongside the new one.
    engine, deps, session = _build_engine()
    session.scalar = AsyncMock(return_value=2)
    prior_active_row = SimpleNamespace(forecast_status="ACTIVE")
    session.scalars = AsyncMock(return_value=[prior_active_row])

    payload = {
        "symbol": "BTC",
        "horizon": "24h",
        "current_price": 100.0,
        "target_price": 103.0,
        "expected_change_pct": 3.0,
        "direction": "Bullish",
        "probability_pct": 70,
        "price_path": [],
        "probability_distribution": [],
        "key_levels": {},
    }
    version = await engine._persist(
        payload,
        datetime(2026, 8, 2, tzinfo=UTC),
        "high",
        regime_at_forecast="bull",
        is_official_daily=False,
        confidence_breakdown=[],
    )

    assert version == 3
    assert prior_active_row.forecast_status == "SUPERSEDED"
    session.add.assert_called_once()  # the new row -- the old one is UPDATEd, not re-inserted


async def test_persist_official_daily_skips_insert_when_todays_row_already_exists():
    # Forecasting 2.0 (Part 2/4): a retried/duplicate scheduler tick for
    # the same (symbol, horizon, UTC date) must be a graceful no-op --
    # returns the existing row's own version, never a second INSERT (the
    # DB's own partial unique index is the real backstop; this is the
    # engine-side check that avoids ever hitting it).
    engine, deps, session = _build_engine()
    existing_row = SimpleNamespace(forecast_version=5)
    session.scalar = AsyncMock(return_value=existing_row)

    payload = {
        "symbol": "BTC",
        "horizon": "24h",
        "current_price": 100.0,
        "target_price": 103.0,
        "expected_change_pct": 3.0,
        "direction": "Bullish",
        "probability_pct": 70,
        "price_path": [],
        "probability_distribution": [],
        "key_levels": {},
    }
    version = await engine._persist(
        payload,
        datetime(2026, 8, 2, tzinfo=UTC),
        "high",
        regime_at_forecast="bull",
        is_official_daily=True,
        confidence_breakdown=[],
    )

    assert version == 5
    session.add.assert_not_called()


async def test_persist_official_daily_inserts_and_stamps_official_fields_when_none_exists():
    engine, deps, session = _build_engine()
    session.scalar = AsyncMock(side_effect=[None, 2])  # no existing official row; prior_version=2

    payload = {
        "symbol": "SOL",
        "horizon": "24h",
        "current_price": 100.0,
        "target_price": 103.0,
        "expected_change_pct": 3.0,
        "direction": "Bullish",
        "probability_pct": 70,
        "price_path": [],
        "probability_distribution": [],
        "key_levels": {},
    }
    version = await engine._persist(
        payload,
        datetime(2026, 8, 2, tzinfo=UTC),
        "high",
        regime_at_forecast="bull",
        is_official_daily=True,
        confidence_breakdown=[],
    )

    assert version == 3
    added = session.add.call_args[0][0]
    assert added.is_official_daily is True
    assert added.official_forecast_date == datetime.now(UTC).date()


async def test_persist_stamps_the_current_forecast_model_version():
    # Final audit (Phase 22): every persisted row must carry the module's
    # current FORECAST_MODEL_VERSION tag, not leave it None -- None is
    # reserved for rows persisted before this column existed.
    engine, deps, session = _build_engine()
    session.scalar = AsyncMock(return_value=None)

    payload = {
        "symbol": "BTC",
        "horizon": "24h",
        "current_price": 100.0,
        "target_price": 103.0,
        "expected_change_pct": 3.0,
        "direction": "Bullish",
        "probability_pct": 70,
        "price_path": [],
        "probability_distribution": [],
        "key_levels": {},
    }
    await engine._persist(
        payload,
        datetime(2026, 8, 2, tzinfo=UTC),
        "high",
        regime_at_forecast=None,
        is_official_daily=False,
        confidence_breakdown=[],
    )

    added = session.add.call_args[0][0]
    assert added.model_version == FORECAST_MODEL_VERSION


# ---- Forecasting 2.0: Agent Performance (Part 26) --------------------------


def test_aggregate_agent_performance_groups_by_agent_and_symbol():
    graded = [
        ("Technical Analysis", "BTC", True),
        ("Technical Analysis", "BTC", True),
        ("Technical Analysis", "BTC", False),
        ("News", "BTC", True),
    ]
    results = aggregate_agent_performance(graded, min_sample_size=2)

    by_agent = {(r["agent_name"], r["symbol"]): r for r in results}
    technical = by_agent[("Technical Analysis", "BTC")]
    assert technical["sample_size"] == 3
    assert technical["accuracy_pct"] == pytest.approx(66.7, abs=0.1)
    assert technical["insufficient_sample"] is False

    news = by_agent[("News", "BTC")]
    assert news["sample_size"] == 1
    assert news["accuracy_pct"] is None
    assert news["insufficient_sample"] is True


def test_aggregate_agent_performance_empty_input():
    assert aggregate_agent_performance([], min_sample_size=10) == []


async def test_get_agent_performance_joins_agent_forecasts_to_graded_outcomes():
    engine, deps, session = _build_engine()
    session.execute = AsyncMock(
        return_value=[
            SimpleNamespace(agent_name="Technical Analysis", symbol="BTC", direction_correct=True),
            SimpleNamespace(agent_name="Technical Analysis", symbol="BTC", direction_correct=False),
        ]
    )

    with patch(
        "app.services.forecast.engine.get_settings",
        return_value=SimpleNamespace(agent_performance_min_sample_size=1),
    ):
        results = await engine.get_agent_performance(("BTC",))

    assert results == [
        {
            "agent_name": "Technical Analysis",
            "symbol": "BTC",
            "sample_size": 2,
            "accuracy_pct": 50.0,
            "insufficient_sample": False,
        }
    ]


# ---- Forecasting 2.0: Error Lab (Part 27/28) --------------------------------


async def test_get_error_lab_returns_wrong_forecasts_with_linked_agent_evidence():
    engine, deps, session = _build_engine()
    wrong_forecast = SimpleNamespace(id=42, symbol="BTC", direction_correct=False)
    agent_row = SimpleNamespace(forecast_id=42, agent_name="Technical Analysis", confidence_pct=70)
    session.scalars = AsyncMock(side_effect=[[wrong_forecast], [agent_row]])

    entries = await engine.get_error_lab(("BTC",), limit=20)

    assert len(entries) == 1
    assert entries[0]["forecast"] is wrong_forecast
    assert entries[0]["agents"] == [agent_row]


async def test_get_error_lab_returns_empty_without_a_second_query_when_nothing_wrong():
    engine, deps, session = _build_engine()
    session.scalars = AsyncMock(return_value=[])

    entries = await engine.get_error_lab(("BTC",), limit=20)

    assert entries == []
    session.scalars.assert_awaited_once()  # no second (agent-evidence) query fired


# ---- Forecasting 2.0: Learning Center (Part 33 / Page 7) --------------------


def test_derive_learning_insights_none_with_only_one_qualifying_regime():
    graded = [
        ("Technical Analysis", "BTC", "risk_on", True),
        ("Technical Analysis", "BTC", "risk_on", True),
        ("Technical Analysis", "BTC", "risk_on", False),
        ("Technical Analysis", "BTC", "risk_off", True),  # only 1 obs -- doesn't qualify
    ]
    assert derive_learning_insights(graded, min_sample_size=3, min_gap_pct=15.0) == []


def test_derive_learning_insights_none_when_gap_too_small():
    # Both regimes qualify (3 obs each) but accuracy is identical (66.7%
    # vs 66.7%) -- no real gap to report.
    graded = (
        [("Technical Analysis", "BTC", "risk_on", True)] * 2
        + [("Technical Analysis", "BTC", "risk_on", False)]
        + [("Technical Analysis", "BTC", "risk_off", True)] * 2
        + [("Technical Analysis", "BTC", "risk_off", False)]
    )
    assert derive_learning_insights(graded, min_sample_size=3, min_gap_pct=15.0) == []


def test_derive_learning_insights_emits_statement_when_gap_and_samples_qualify():
    graded = (
        [("Technical Analysis", "BTC", "risk_on", True)] * 4  # 4/4 = 100%
        + [("Technical Analysis", "BTC", "risk_off", True)]
        + [("Technical Analysis", "BTC", "risk_off", False)] * 3  # 1/4 = 25%
    )
    insights = derive_learning_insights(graded, min_sample_size=4, min_gap_pct=15.0)

    assert len(insights) == 1
    insight = insights[0]
    assert insight["agent_name"] == "Technical Analysis"
    assert insight["symbol"] == "BTC"
    assert insight["better_regime"] == "risk_on"
    assert insight["better_accuracy_pct"] == 100.0
    assert insight["better_sample_size"] == 4
    assert insight["worse_regime"] == "risk_off"
    assert insight["worse_accuracy_pct"] == 25.0
    assert insight["worse_sample_size"] == 4
    assert "risk_on" in insight["statement"]
    assert "risk_off" in insight["statement"]


def test_derive_learning_insights_empty_input():
    assert derive_learning_insights([], min_sample_size=5, min_gap_pct=15.0) == []


async def test_get_learning_insights_joins_agent_forecasts_regime_and_outcome():
    engine, deps, session = _build_engine()
    session.execute = AsyncMock(
        return_value=[
            SimpleNamespace(
                agent_name="Technical Analysis",
                symbol="BTC",
                regime_at_forecast="risk_on",
                direction_correct=True,
            ),
        ]
    )

    with patch(
        "app.services.forecast.engine.get_settings",
        return_value=SimpleNamespace(
            learning_insight_min_sample_size=1, learning_insight_min_gap_pct=15.0
        ),
    ):
        # Only one regime present -- no insight possible, but the join/
        # unpacking itself must not raise.
        insights = await engine.get_learning_insights(("BTC",))

    assert insights == []


# ---- Data Leakage Protection (Phase 23): watchdog as_of bounding -----------


async def test_latest_watchdog_snapshot_bounds_the_query_when_as_of_is_given():
    # Same reasoning/pattern as SentimentEngine.get_latest(as_of=...): a
    # forecast computed for an older reference_timestamp must not silently
    # pull in a WatchdogSnapshot cycle produced after that timestamp.
    engine, deps, session = _build_engine()
    session.scalar = AsyncMock(return_value=None)

    cutoff = datetime(2026, 8, 1, tzinfo=UTC)
    await engine._latest_watchdog_snapshot(cutoff)

    query = session.scalar.call_args[0][0]
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "computed_at <=" in compiled
    assert "2026-08-01" in compiled


async def test_latest_watchdog_snapshot_unbounded_when_as_of_is_none():
    engine, deps, session = _build_engine()
    session.scalar = AsyncMock(return_value=None)

    await engine._latest_watchdog_snapshot()

    query = session.scalar.call_args[0][0]
    compiled = str(query.compile())
    assert "computed_at <=" not in compiled


# ---- Forecasting 2.0: Forecast Details (Page 3) -----------------------------


async def test_get_forecast_detail_returns_snapshot_and_agents():
    engine, deps, session = _build_engine()
    snapshot = SimpleNamespace(id=7, symbol="BTC", is_official_daily=True)
    agent_row = SimpleNamespace(forecast_id=7, agent_name="Technical Analysis")
    session.scalar = AsyncMock(return_value=snapshot)
    session.scalars = AsyncMock(return_value=[agent_row])

    detail = await engine.get_forecast_detail(7)

    assert detail == {"forecast": snapshot, "agents": [agent_row]}


async def test_get_forecast_detail_none_when_id_not_found():
    engine, deps, session = _build_engine()
    session.scalar = AsyncMock(return_value=None)

    detail = await engine.get_forecast_detail(999)

    assert detail is None
    session.scalars.assert_not_called()  # no wasted second query


# ---- Forecasting 2.0: Performance (Page 4) ----------------------------------


def test_summarize_official_performance_empty_input():
    assert summarize_official_performance([]) == {
        "graded_count": 0,
        "direction_accuracy_pct": None,
        "direction_accuracy_ci": None,
        "avg_abs_error_pct": None,
        "target_reached_rate_pct": None,
    }


def test_summarize_official_performance_excludes_missing_error_and_target_fields():
    # Two graded rows: one has error_pct/target_reached, the other (a
    # Neutral call) has neither -- those None fields must not drag the
    # averages/rates down or be silently counted as a miss.
    graded = [
        (True, 2.0, True),
        (False, None, None),
    ]
    result = summarize_official_performance(graded)
    assert result["graded_count"] == 2
    assert result["direction_accuracy_pct"] == 50.0
    assert result["avg_abs_error_pct"] == 2.0
    assert result["target_reached_rate_pct"] == 100.0


def test_summarize_official_performance_averages_absolute_error():
    graded = [(True, -4.0, True), (True, 2.0, False)]
    result = summarize_official_performance(graded)
    assert result["avg_abs_error_pct"] == 3.0  # mean(|-4|, |2|)
    assert result["target_reached_rate_pct"] == 50.0


def test_derive_official_calibration_curve_buckets_by_stated_probability():
    graded = [(65, True), (68, True), (72, False)]
    curve = derive_official_calibration_curve(graded, bin_width=20)
    assert len(curve) == 1
    bucket = curve[0]
    assert bucket["probability_bucket"] == "60-80%"
    assert bucket["count"] == 3
    assert bucket["avg_stated_probability_pct"] == round((65 + 68 + 72) / 3, 2)
    assert bucket["observed_accuracy_pct"] == round(100 * 2 / 3, 2)
    assert bucket["sample_sufficiency"] == "insufficient"  # far below the N=30 floor


def test_derive_official_calibration_curve_empty_input():
    assert derive_official_calibration_curve([], bin_width=20) == []


def test_derive_official_calibration_curve_clamps_100_pct_into_last_bucket():
    curve = derive_official_calibration_curve([(100, True)], bin_width=20)
    assert curve[0]["probability_bucket"] == "80-100%"


def test_derive_regime_performance_breakdown_gates_small_groups():
    graded = [("risk_on", True)] * 2 + [("risk_off", True)] * 5 + [("risk_off", False)] * 3
    result = derive_regime_performance_breakdown(graded, min_sample_size=5)
    assert result == [
        {
            "regime": "risk_off",
            "sample_size": 8,
            "accuracy_pct": 62.5,
            "accuracy_ci": compute_wilson_interval(5, 8),
            "insufficient_sample": False,
        },
        {
            "regime": "risk_on",
            "sample_size": 2,
            "accuracy_pct": None,
            "accuracy_ci": None,
            "insufficient_sample": True,
        },
    ]


def test_derive_regime_performance_breakdown_empty_input():
    assert derive_regime_performance_breakdown([], min_sample_size=5) == []


async def test_get_official_performance_combines_summary_calibration_and_regime():
    engine, deps, session = _build_engine()
    session.execute = AsyncMock(
        return_value=[
            SimpleNamespace(
                symbol="BTC",
                probability_pct=70,
                direction_correct=True,
                error_pct=1.5,
                target_reached=True,
                regime_at_forecast="risk_on",
            ),
            SimpleNamespace(
                symbol="BTC",
                probability_pct=72,
                direction_correct=False,
                error_pct=-3.0,
                target_reached=False,
                regime_at_forecast="risk_on",
            ),
        ]
    )

    with patch(
        "app.services.forecast.engine.get_settings",
        return_value=SimpleNamespace(agent_performance_min_sample_size=1),
    ):
        result = await engine.get_official_performance(("BTC",))

    assert result["summary"]["graded_count"] == 2
    assert result["summary"]["direction_accuracy_pct"] == 50.0
    assert result["by_symbol"]["BTC"]["graded_count"] == 2
    assert result["by_symbol"]["BTC"]["direction_accuracy_pct"] == 50.0
    assert len(result["calibration"]) == 1
    assert result["regime_breakdown"] == [
        {
            "regime": "risk_on",
            "sample_size": 2,
            "accuracy_pct": 50.0,
            "accuracy_ci": compute_wilson_interval(1, 2),
            "insufficient_sample": False,
        }
    ]


async def test_get_official_performance_since_filters_by_evaluated_at():
    # Forecast weekly review digest: since= must add an evaluated_at
    # filter to the query (not computed_at -- see the docstring), and
    # omitting it must leave the query exactly as before.
    engine, deps, session = _build_engine()
    session.execute = AsyncMock(return_value=[])

    with patch(
        "app.services.forecast.engine.get_settings",
        return_value=SimpleNamespace(agent_performance_min_sample_size=1),
    ):
        await engine.get_official_performance(("BTC",))
        query_without_since = str(session.execute.call_args.args[0])

        await engine.get_official_performance(("BTC",), since=datetime(2026, 8, 10, tzinfo=UTC))
        query_with_since = str(session.execute.call_args.args[0])

    assert "evaluated_at" not in query_without_since
    assert "evaluated_at" in query_with_since


def test_summarize_official_performance_by_symbol_groups_independently():
    graded = [
        ("BTC", True, 1.0, True),
        ("BTC", False, -2.0, False),
        ("SOL", True, 0.5, True),
    ]
    result = summarize_official_performance_by_symbol(graded)
    assert set(result.keys()) == {"BTC", "SOL"}
    assert result["BTC"]["graded_count"] == 2
    assert result["BTC"]["direction_accuracy_pct"] == 50.0
    assert result["SOL"]["graded_count"] == 1
    assert result["SOL"]["direction_accuracy_pct"] == 100.0
    # each symbol's own Wilson CI, not one pooled across symbols
    assert result["BTC"]["direction_accuracy_ci"] == compute_wilson_interval(1, 2)
    assert result["SOL"]["direction_accuracy_ci"] == compute_wilson_interval(1, 1)


def test_summarize_official_performance_by_symbol_empty_input():
    assert summarize_official_performance_by_symbol([]) == {}


async def test_get_official_history_paginates_with_offset():
    engine, deps, session = _build_engine()
    session.scalars = AsyncMock(return_value=[])

    await engine.get_official_history("BTC", limit=10, offset=20)

    query = session.scalars.call_args.args[0]
    compiled = query.compile(compile_kwargs={"literal_binds": True})
    assert "LIMIT 10" in str(compiled)
    assert "OFFSET 20" in str(compiled)


async def test_get_official_history_filters_by_date_range():
    engine, deps, session = _build_engine()
    session.scalars = AsyncMock(return_value=[])

    await engine.get_official_history("BTC", date_from=date(2026, 1, 1), date_to=date(2026, 1, 31))

    query_str = str(session.scalars.call_args.args[0])
    assert "official_forecast_date" in query_str


async def test_get_official_history_omits_date_filters_when_not_given():
    engine, deps, session = _build_engine()
    session.scalars = AsyncMock(return_value=[])

    await engine.get_official_history("BTC")

    query_str = str(session.scalars.call_args.args[0])
    assert "official_forecast_date >=" not in query_str
    assert "official_forecast_date <=" not in query_str
