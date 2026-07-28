from app.services.common.scoring import direction_from_score


def test_direction_from_score_returns_none_for_none_input():
    assert direction_from_score(None) == (None, None)


def test_direction_from_score_bullish_above_center():
    direction, confidence = direction_from_score(75.0)
    assert direction == "bullish"
    assert confidence == 50.0


def test_direction_from_score_bearish_below_center():
    direction, confidence = direction_from_score(25.0)
    assert direction == "bearish"
    assert confidence == 50.0


def test_direction_from_score_neutral_at_center():
    direction, confidence = direction_from_score(50.0)
    assert direction == "neutral"
    assert confidence == 0.0


def test_direction_from_score_confidence_clamped_to_100():
    direction, confidence = direction_from_score(200.0)
    assert direction == "bullish"
    assert confidence == 100.0


def test_direction_from_score_respects_custom_center():
    direction, confidence = direction_from_score(80.0, center=70.0)
    assert direction == "bullish"
    assert confidence > 0
