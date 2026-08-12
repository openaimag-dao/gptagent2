import math
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.analysis.regime import MarketRegime
from app.services.forecast.engine import (
    ForecastEngine,
    _correlation_confidence,
    _distance_from_neutral,
    _onchain_confidence,
    _whale_confidence,
    classify_direction_label,
    compute_expected_max_drawdown_pct,
    compute_momentum_score,
    compute_prediction_range,
    compute_price_path,
    compute_price_target,
    compute_probability_distribution,
    compute_scenario_cases,
    derive_regime_label,
    derive_risk_meter,
    grade_confidence,
    grade_direction,
    grade_price_forecasts,
    price_forecast_quality_multiplier,
    summarize_forecast_accuracy,
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
        "quality_multiplier": None,
        "adjusted_confidence_pct": None,
    }
    session.add.assert_called_once()
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
    rows = [SimpleNamespace(timestamp=ts0, close=100.0)]
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


async def test_grade_price_forecasts_grades_an_elapsed_row():
    ts0 = datetime(2026, 8, 1, tzinfo=UTC)
    rows = [
        SimpleNamespace(timestamp=ts0, close=100.0, atr=2.0),
        SimpleNamespace(timestamp=ts0 + timedelta(days=1), close=105.0, atr=2.0),
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
    session.commit.assert_awaited()


async def test_grade_price_forecasts_skips_an_unmatched_reference_timestamp():
    rows = [SimpleNamespace(timestamp=datetime(2026, 8, 1, tzinfo=UTC), close=100.0)]
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
        SimpleNamespace(error_pct=1.0),
        SimpleNamespace(error_pct=-3.0),
    ]
    session_factory, _ = _forecast_session(graded_rows)
    summary = await summarize_forecast_accuracy(session_factory, "BTC", "24h")
    assert summary == {"evaluated_count": 2, "avg_abs_error_pct": 2.0}
