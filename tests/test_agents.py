from app.services.agents.news_agent import estimate_impact


def test_estimate_impact_high_for_strong_weighted_fed_news():
    assert estimate_impact(sentiment_score=5.0, category="federal_reserve") == "high"


def test_estimate_impact_low_for_weak_crypto_news():
    assert estimate_impact(sentiment_score=1.0, category="crypto") == "low"


def test_estimate_impact_medium_band():
    assert estimate_impact(sentiment_score=2.5, category="crypto") == "medium"


def test_estimate_impact_unknown_category_uses_default_weight():
    assert estimate_impact(sentiment_score=7.0, category="unknown") == "high"
