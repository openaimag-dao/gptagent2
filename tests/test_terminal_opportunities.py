from app.services.terminal.opportunities import classify_opportunity, score_opportunity


def test_score_opportunity_none_when_no_signal_available():
    assert score_opportunity(None, None, None, None) is None


def test_score_opportunity_uses_probability_edge_only():
    # edge=+40 -> center_scaled(40, 0.5) = 50 + 20 = 70
    score = score_opportunity(40.0, None, None, None)

    assert score == 70.0


def test_score_opportunity_bullish_breakout_raises_score():
    score = score_opportunity(None, 80.0, "bullish", None)

    assert score == 80.0


def test_score_opportunity_bearish_breakout_lowers_score():
    score = score_opportunity(None, 80.0, "bearish", None)

    assert score == 20.0


def test_score_opportunity_advisor_recommendation_component():
    assert score_opportunity(None, None, None, "BUY") == 80.0
    assert score_opportunity(None, None, None, "HOLD") == 50.0
    assert score_opportunity(None, None, None, "SELL") == 20.0


def test_score_opportunity_combines_all_three_signals():
    # probability: edge=100 -> 100; breakout: bullish 100 -> 100; advisor: BUY -> 80
    # weighted_average([100,100,80], weights=[40,35,25]) = (4000+3500+2000)/100 = 95.0
    score = score_opportunity(100.0, 100.0, "bullish", "BUY")

    assert score == 95.0


def test_classify_opportunity_bullish():
    assert classify_opportunity(75.0) == "bullish"
    assert classify_opportunity(60.0) == "bullish"


def test_classify_opportunity_bearish():
    assert classify_opportunity(25.0) == "bearish"
    assert classify_opportunity(40.0) == "bearish"


def test_classify_opportunity_neutral():
    assert classify_opportunity(50.0) == "neutral"
    assert classify_opportunity(45.0) == "neutral"
