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


def test_direction_from_score_confidence_is_rounded_not_a_float_artifact():
    """Reproduces the exact input shape technical_agent.py feeds this
    function (bullish/bearish scores already rounded to 1 decimal, e.g.
    70.1/29.9): 70.1 - 29.9 is not exactly representable in binary
    floating point, so the unrounded confidence used to come out as
    40.19999999999999 and render that way on the Committee page's
    Supporting Evidence table instead of 40.2."""
    score = 50.0 + (70.1 - 29.9) / 2.0
    _, confidence = direction_from_score(score)
    assert confidence == 40.2
