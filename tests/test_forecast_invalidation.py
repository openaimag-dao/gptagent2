from app.services.forecast.invalidation import (
    evaluate_invalidation,
    evaluate_price_invalidation,
    evaluate_regime_invalidation,
)


def test_price_invalidation_none_for_neutral_direction():
    assert evaluate_price_invalidation("Neutral", 95.0, 90.0) is None


def test_price_invalidation_none_without_level_or_price():
    assert evaluate_price_invalidation("Bullish", None, 90.0) is None
    assert evaluate_price_invalidation("Bullish", 95.0, None) is None


def test_price_invalidation_triggers_when_bullish_breaks_below_support():
    rule = evaluate_price_invalidation("Bullish", 95.0, 90.0)
    assert rule is not None
    assert rule.rule_type == "price_breaches_invalidation_level"
    assert rule.triggered is True


def test_price_invalidation_does_not_trigger_when_bullish_holds_above_support():
    rule = evaluate_price_invalidation("Strong Bullish", 95.0, 100.0)
    assert rule.triggered is False


def test_price_invalidation_triggers_when_bearish_breaks_above_resistance():
    rule = evaluate_price_invalidation("Bearish", 105.0, 110.0)
    assert rule.triggered is True


def test_price_invalidation_does_not_trigger_when_bearish_holds_below_resistance():
    rule = evaluate_price_invalidation("Strong Bearish", 105.0, 100.0)
    assert rule.triggered is False


def test_regime_invalidation_none_without_both_regimes():
    assert evaluate_regime_invalidation(None, "bull") is None
    assert evaluate_regime_invalidation("bull", None) is None


def test_regime_invalidation_triggers_on_change():
    rule = evaluate_regime_invalidation("bull", "bear")
    assert rule.rule_type == "regime_changed"
    assert rule.triggered is True


def test_regime_invalidation_does_not_trigger_when_unchanged():
    rule = evaluate_regime_invalidation("bull", "bull")
    assert rule.triggered is False


def test_evaluate_invalidation_active_when_nothing_triggers():
    result = evaluate_invalidation(
        direction="Bullish",
        invalidation_level=95.0,
        current_price=100.0,
        regime_at_forecast="bull",
        current_regime="bull",
    )
    assert result["status"] == "ACTIVE"
    assert result["invalidation_reason"] is None
    assert len(result["checked_rules"]) == 2


def test_evaluate_invalidation_invalidated_when_price_rule_fires():
    result = evaluate_invalidation(
        direction="Bullish",
        invalidation_level=95.0,
        current_price=90.0,
        regime_at_forecast="bull",
        current_regime="bull",
    )
    assert result["status"] == "INVALIDATED"
    assert "invalidation level" in result["invalidation_reason"]


def test_evaluate_invalidation_invalidated_when_regime_rule_fires():
    result = evaluate_invalidation(
        direction="Bullish",
        invalidation_level=95.0,
        current_price=100.0,
        regime_at_forecast="bull",
        current_regime="bear",
    )
    assert result["status"] == "INVALIDATED"
    assert "Regime changed" in result["invalidation_reason"]


def test_evaluate_invalidation_active_when_no_rule_is_checkable():
    # Neutral direction (no price rule) and no regime data at all.
    result = evaluate_invalidation(
        direction="Neutral",
        invalidation_level=95.0,
        current_price=100.0,
        regime_at_forecast=None,
        current_regime=None,
    )
    assert result["status"] == "ACTIVE"
    assert result["checked_rules"] == []
