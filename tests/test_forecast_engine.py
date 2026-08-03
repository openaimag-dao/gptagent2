import math
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
    compute_price_path,
    compute_price_target,
    compute_probability_distribution,
    derive_regime_label,
    derive_risk_meter,
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
    }
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


async def test_compute_builds_full_payload_and_persists():
    engine, deps, session = _build_engine()
    history_row = SimpleNamespace(close=100.0, atr=2.0)
    probability_snapshot = SimpleNamespace(
        prob_up_pct=70,
        prob_down_pct=10,
        prob_flat_pct=20,
        sample_size=50,
        avg_forward_return_pct=3.0,
    )
    deps["probability_engine"].compute_and_store.return_value = probability_snapshot
    deps["quality_engine"].evaluate.return_value = None
    deps["technical_engine"].get_latest.return_value = SimpleNamespace(
        confidence=80.0, trend_strength=45.0, support=95.0, resistance=105.0
    )
    deps["explanation_engine"].build.return_value = {"indicators": [{"name": "rsi", "points": 2}]}
    deps["economic_calendar_engine"].get_upcoming.return_value = []
    deps["sentiment_engine"].get_latest.return_value = SimpleNamespace(
        news_sentiment_score=70, global_sentiment_score=65
    )
    deps["correlation_engine"].get_latest.return_value = []
    deps["whale_engine"].get_snapshot.return_value = {"available": False}
    deps["onchain_engine"].get_snapshot.return_value = {"available": False, "metrics": {}}

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
    session.add.assert_called_once()
    session.commit.assert_awaited()
