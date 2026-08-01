from datetime import UTC, datetime, timedelta

from app.services.watchdog.detectors import (
    classify_bias,
    classify_market_health,
    detect_all_changes,
    detect_committee_change,
    detect_confidence_change,
    detect_liquidity_shift,
    detect_regime_changed_event,
    detect_risk_change,
    detect_trend_strength_change,
    detect_volatility_spike,
    freshness_status,
    is_telegram_eligible,
)


def test_classify_market_health():
    assert classify_market_health(None) == "Unknown"
    assert classify_market_health(80) == "Healthy"
    assert classify_market_health(50) == "Watch"
    assert classify_market_health(20) == "Stressed"


def test_classify_bias():
    assert classify_bias(None, None) is None
    assert classify_bias(70.0, 30.0) == "Bullish"
    assert classify_bias(30.0, 70.0) == "Bearish"
    assert classify_bias(50.0, 50.0) == "Neutral"


def test_freshness_status():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert freshness_status(None, 3600, now) == "unavailable"
    assert freshness_status(now - timedelta(minutes=5), 3600, now) == "ok"
    assert freshness_status(now - timedelta(hours=3), 3600, now) == "stale"


def test_detect_trend_strength_change_thresholds():
    assert detect_trend_strength_change(50, 55) is None
    increased = detect_trend_strength_change(50, 65)
    assert increased["event_type"] == "TrendStrengthIncreased"
    decreased = detect_trend_strength_change(65, 50)
    assert decreased["event_type"] == "TrendStrengthDecreased"
    assert detect_trend_strength_change(None, 65) is None


def test_detect_confidence_change_thresholds():
    assert detect_confidence_change(80, 90) is None
    assert detect_confidence_change(80, 60)["event_type"] == "ConfidenceDropped"
    assert detect_confidence_change(60, 90)["event_type"] == "ConfidenceIncreased"


def test_detect_risk_change_labels_rising_risk_as_increased():
    increased = detect_risk_change(30, 50)
    assert increased["event_type"] == "RiskIncreased"
    reduced = detect_risk_change(50, 30)
    assert reduced["event_type"] == "RiskReduced"


def test_detect_liquidity_shift_either_direction():
    assert detect_liquidity_shift(50, 55) is None
    up = detect_liquidity_shift(40, 60)
    assert up["event_type"] == "LiquidityShift"
    assert up["data"]["direction"] == "up"
    down = detect_liquidity_shift(60, 40)
    assert down["data"]["direction"] == "down"


def test_detect_volatility_spike_only_fires_on_increase():
    assert detect_volatility_spike(50, 40) is None
    assert detect_volatility_spike(50, 51) is None
    spike = detect_volatility_spike(20, 40)
    assert spike["event_type"] == "VolatilitySpike"


def test_detect_committee_change():
    assert detect_committee_change(None, "BUY") is None
    assert detect_committee_change("BUY", "BUY") is None
    changed = detect_committee_change("HOLD", "SELL")
    assert changed["event_type"] == "CommitteeChanged"
    assert changed["data"] == {"prev": "HOLD", "curr": "SELL"}


def test_detect_regime_changed_event():
    assert detect_regime_changed_event(None, "risk_on") is None
    assert detect_regime_changed_event("risk_on", "risk_on") is None
    changed = detect_regime_changed_event("risk_on", "risk_off")
    assert changed["event_type"] == "MarketRegimeChanged"


def test_is_telegram_eligible_only_for_mission_listed_events():
    assert is_telegram_eligible("MarketRegimeChanged") is True
    assert is_telegram_eligible("CommitteeChanged") is True
    assert is_telegram_eligible("ConfidenceIncreased") is True
    assert is_telegram_eligible("RiskIncreased") is True
    assert is_telegram_eligible("RiskReduced") is False
    assert is_telegram_eligible("TrendStrengthIncreased") is False
    assert is_telegram_eligible("VolatilitySpike") is False


def test_detect_all_changes_none_on_first_cycle():
    assert detect_all_changes(None, {"regime": "risk_on"}) == []


def test_detect_all_changes_collects_every_fired_detector():
    previous = {
        "regime": "risk_on",
        "trend_strength_score": 40,
        "confidence_score": 80,
        "risk_score": 30,
        "liquidity_score": 50,
        "volatility": 20.0,
        "committee_decision": "BUY",
    }
    current = {
        "regime": "risk_off",
        "trend_strength_score": 60,
        "confidence_score": 55,
        "risk_score": 55,
        "liquidity_score": 50,
        "volatility": 45.0,
        "committee_decision": "SELL",
    }
    events = detect_all_changes(previous, current)
    event_types = {e["event_type"] for e in events}
    assert event_types == {
        "MarketRegimeChanged",
        "TrendStrengthIncreased",
        "ConfidenceDropped",
        "RiskIncreased",
        "VolatilitySpike",
        "CommitteeChanged",
    }


def test_detect_all_changes_empty_when_nothing_moved():
    reading = {
        "regime": "risk_on",
        "trend_strength_score": 50,
        "confidence_score": 70,
        "risk_score": 40,
        "liquidity_score": 60,
        "volatility": 25.0,
        "committee_decision": "HOLD",
    }
    assert detect_all_changes(reading, dict(reading)) == []
