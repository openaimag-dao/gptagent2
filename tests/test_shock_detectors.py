from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.shocks.detectors import (
    best_window_detection,
    classify_tier,
    committee_alignment_score,
    compute_realized_volatility,
    compute_window_changes,
    consensus_alignment_score,
    decide_alert_action,
    detect_multi_asset_shock,
    gate_severity,
    historical_similarity_score,
    regime_alignment_score,
    regime_direction_bucket,
    score_alert_quality,
    should_notify,
    volatility_score,
    volume_change_score,
)


def test_classify_tier_below_info_is_none():
    assert classify_tier("BTC", 1.0) is None


def test_classify_tier_picks_highest_cleared_threshold():
    assert classify_tier("BTC", 3.5) == "info"
    assert classify_tier("BTC", 5.5) == "important"
    assert classify_tier("BTC", 8.5) == "high"
    assert classify_tier("BTC", 11.0) == "critical"


def test_classify_tier_uses_magnitude_not_sign():
    assert classify_tier("BTC", -9.0) == "high"


def test_classify_tier_unknown_symbol_is_none():
    assert classify_tier("DOGE", 50.0) is None


def test_best_window_detection_none_when_nothing_clears_info():
    result = best_window_detection("BTC", {"5m": 0.1, "15m": None, "1h": 1.0})
    assert result is None


def test_best_window_detection_prefers_highest_tier():
    result = best_window_detection("BTC", {"5m": 3.5, "1h": 9.0})  # 5m=info, 1h=high -- high wins
    assert result == {"symbol": "BTC", "window": "1h", "pct_change": 9.0, "tier": "high"}


def test_best_window_detection_prefers_shorter_window_on_tie():
    result = best_window_detection(
        "BTC", {"5m": 6.0, "1h": 6.5}
    )  # both "important" tier -- shorter window wins
    assert result["window"] == "5m"


def test_detect_multi_asset_shock_none_below_min_count():
    detections = {
        "BTC": {"symbol": "BTC", "pct_change": -6.0, "tier": "important"},
        "ETH": {"symbol": "ETH", "pct_change": -6.0, "tier": "important"},
        "SOL": None,
        "NASDAQ": None,
        "SPX": None,
        "DJI": None,
    }
    assert detect_multi_asset_shock(detections) is None


def test_detect_multi_asset_shock_fires_on_synchronized_down_move():
    detections = {
        "BTC": {"symbol": "BTC", "pct_change": -6.0, "tier": "important"},
        "ETH": {"symbol": "ETH", "pct_change": -7.0, "tier": "high"},
        "SOL": {"symbol": "SOL", "pct_change": -9.0, "tier": "important"},
        "NASDAQ": None,
        "SPX": None,
        "DJI": None,
    }
    result = detect_multi_asset_shock(detections)
    assert result is not None
    assert result["category"] == "multi_asset_shock"
    assert result["direction"] == "down"
    assert result["tier"] == "critical"  # escalated one step beyond the worst individual (high)
    assert len(result["moves"]) == 3


def test_detect_multi_asset_shock_ignores_below_min_tier():
    detections = {
        "BTC": {"symbol": "BTC", "pct_change": -3.5, "tier": "info"},
        "ETH": {"symbol": "ETH", "pct_change": -3.5, "tier": "info"},
        "SOL": {"symbol": "SOL", "pct_change": -5.5, "tier": "info"},
        "NASDAQ": None,
        "SPX": None,
        "DJI": None,
    }
    assert detect_multi_asset_shock(detections) is None


def test_detect_multi_asset_shock_mixed_directions_takes_larger_group():
    detections = {
        "BTC": {"symbol": "BTC", "pct_change": -6.0, "tier": "important"},
        "ETH": {"symbol": "ETH", "pct_change": -6.0, "tier": "important"},
        "SOL": {"symbol": "SOL", "pct_change": -9.0, "tier": "important"},
        "NASDAQ": {"symbol": "NASDAQ", "pct_change": 3.5, "tier": "important"},
        "SPX": None,
        "DJI": None,
    }
    result = detect_multi_asset_shock(detections)
    assert result["direction"] == "down"
    assert len(result["moves"]) == 3


def test_score_alert_quality_excludes_none_components():
    score = score_alert_quality(
        {
            "volume": 80.0,
            "volatility": None,
            "regime_alignment": 100.0,
            "trend_strength": None,
            "consensus_alignment": None,
            "committee_alignment": None,
            "historical_similarity": None,
            "risk_score": None,
            "confidence_score": None,
        }
    )
    assert score is not None
    assert 0 <= score <= 100


def test_score_alert_quality_none_when_all_missing():
    components = {
        "volume": None,
        "volatility": None,
        "regime_alignment": None,
        "trend_strength": None,
        "consensus_alignment": None,
        "committee_alignment": None,
        "historical_similarity": None,
        "risk_score": None,
        "confidence_score": None,
    }
    assert score_alert_quality(components) is None


def test_gate_severity_downgrades_one_step_on_low_quality():
    assert gate_severity("critical", 10.0) == "high"
    assert gate_severity("high", 10.0) == "important"
    assert gate_severity("info", 10.0) == "info"  # floor, never goes below info


def test_gate_severity_unchanged_on_good_quality():
    assert gate_severity("critical", 90.0) == "critical"


def test_gate_severity_unchanged_when_quality_unavailable():
    assert gate_severity("high", None) == "high"


def test_should_notify_only_high_and_critical():
    assert should_notify("info") is False
    assert should_notify("important") is False
    assert should_notify("high") is True
    assert should_notify("critical") is True


def test_decide_alert_action_new_when_no_active_episode():
    assert decide_alert_action(False, None, "high", datetime.now(UTC), None) == "new"


def test_decide_alert_action_escalate_on_higher_tier():
    now = datetime.now(UTC)
    result = decide_alert_action(True, "high", "critical", now, now - timedelta(minutes=5))
    assert result == "escalate"


def test_decide_alert_action_suppress_on_same_or_lower_tier():
    now = datetime.now(UTC)
    assert decide_alert_action(True, "high", "high", now, now - timedelta(minutes=5)) == "suppress"
    assert (
        decide_alert_action(True, "high", "important", now, now - timedelta(minutes=5))
        == "suppress"
    )


def test_decide_alert_action_resolves_stale_episode():
    now = datetime.now(UTC)
    result = decide_alert_action(
        True, "high", "high", now, now - timedelta(minutes=180), resolve_after_minutes=120
    )
    assert result == "resolve_then_new"


def test_compute_realized_volatility_none_with_too_few_points():
    assert compute_realized_volatility([100.0, 101.0]) is None


def test_compute_realized_volatility_zero_for_flat_prices():
    assert compute_realized_volatility([100.0, 100.0, 100.0, 100.0]) == 0.0


def test_compute_realized_volatility_positive_for_swinging_prices():
    result = compute_realized_volatility([100.0, 105.0, 98.0, 103.0])
    assert result is not None
    assert result > 0


def test_regime_direction_bucket_classifies_labels():
    assert regime_direction_bucket("bear") == "bearish"
    assert regime_direction_bucket("strong_bull") == "bullish"
    assert regime_direction_bucket("sideways") == "neutral"
    assert regime_direction_bucket(None) == "neutral"


def _row(price: float, minutes_ago: int, now: datetime) -> SimpleNamespace:
    return SimpleNamespace(price=price, recorded_at=now - timedelta(minutes=minutes_ago))


def test_compute_window_changes_empty_history_returns_all_none():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    changes = compute_window_changes([], now, windows={"15m": 15, "1h": 60})
    assert changes == {"15m": None, "1h": None}


def test_compute_window_changes_picks_nearest_row_per_window():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    history = [
        _row(100.0, 65, now),
        _row(110.0, 16, now),
        _row(120.0, 0, now),
    ]
    changes = compute_window_changes(history, now, windows={"15m": 15, "1h": 60})
    assert changes["15m"] == (120.0 - 110.0) / 110.0 * 100
    assert changes["1h"] == (120.0 - 100.0) / 100.0 * 100


def test_regime_alignment_score_matches_direction():
    assert regime_alignment_score("bear", "bearish") == 100.0
    assert regime_alignment_score("bear", "bullish") == 0.0
    assert regime_alignment_score("risk_on", "bullish") == 100.0
    assert regime_alignment_score("sideways", "bullish") == 50.0
    assert regime_alignment_score(None, "bullish") is None


def test_consensus_alignment_score():
    assert consensus_alignment_score(70.0, 30.0, 70.0, "bullish") == 70.0
    assert consensus_alignment_score(70.0, 30.0, 70.0, "bearish") == 30.0
    assert consensus_alignment_score(None, 30.0, 70.0, "bearish") is None


def test_committee_alignment_score():
    assert committee_alignment_score("SELL", 65.0, "bearish") == 65.0
    assert committee_alignment_score("SELL", 65.0, "bullish") == 35.0
    assert committee_alignment_score("HOLD", 50.0, "bullish") == 50.0
    assert committee_alignment_score(None, None, "bullish") is None


def test_historical_similarity_score():
    assert historical_similarity_score([1.0, 2.0, -1.0, 3.0], "bullish") == 75.0
    assert historical_similarity_score([], "bullish") is None
    assert historical_similarity_score([None, None], "bullish") is None


def test_volume_change_score():
    assert volume_change_score(50.0) == 100.0
    assert volume_change_score(-50.0) == 0.0
    assert volume_change_score(None) is None


def test_volatility_score_saturates():
    assert volatility_score(20.0, scale=10.0) == 100.0
    assert volatility_score(0.0, scale=10.0) == 0.0
    assert volatility_score(None) is None
