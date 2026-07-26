from app.database.models import AlertLog
from app.services.research.researcher import _format_discoveries


def _alert(alert_type: str, confidence_pct: int, tier: str = "strong") -> AlertLog:
    return AlertLog(
        alert_type=alert_type,
        message=f"{alert_type} message",
        conviction_tier=tier,
        confidence_pct=confidence_pct,
        broadcast=True,
    )


def test_format_discoveries_empty():
    assert _format_discoveries([]) == "No detections in this window."


def test_format_discoveries_lists_each_entry():
    discoveries = [_alert("regime_change", 90), _alert("correlation_break", 70)]
    result = _format_discoveries(discoveries)
    assert "regime_change" in result
    assert "correlation_break" in result
    assert "90%" in result
    assert "70%" in result
