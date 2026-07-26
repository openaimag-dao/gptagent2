from app.services.conviction.engine import classify_conviction


def test_low_confidence_is_weak():
    result = classify_conviction(10)
    assert result["tier"] == "Weak"
    assert result["alert_eligible"] is False


def test_medium_band():
    result = classify_conviction(45)
    assert result["tier"] == "Medium"


def test_strong_band_is_alert_eligible():
    result = classify_conviction(70)
    assert result["tier"] == "Strong"
    assert result["alert_eligible"] is True


def test_very_strong_without_sample_size():
    result = classify_conviction(90)
    assert result["tier"] == "Very Strong"


def test_high_confidence_without_sample_size_never_reaches_institutional():
    result = classify_conviction(99)
    assert result["tier"] == "Very Strong"


def test_high_confidence_with_large_sample_reaches_institutional():
    result = classify_conviction(99, sample_size=100)
    assert result["tier"] == "Institutional"


def test_high_confidence_with_small_sample_is_scaled_down():
    result = classify_conviction(99, sample_size=2, min_sample_size=30)
    assert result["tier"] in ("Weak", "Medium")
    assert result["effective_confidence_pct"] < 99
