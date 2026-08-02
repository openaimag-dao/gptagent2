from unittest.mock import AsyncMock

from app.database.models import (
    MarketRegimeSnapshot,
    NewsCategory,
    NewsItem,
    NewsSentiment,
    ScenarioSnapshot,
    SignalSnapshot,
)
from app.services.analysis.regime import MarketRegime
from app.services.explanation.engine import ExplanationEngine, condense_explanation


class _StubExplanationEngine(ExplanationEngine):
    """Avoids a real DB round-trip for the one method that queries directly."""

    async def _recent_similar_matches(self, symbol):
        return []


def _news(sentiment: NewsSentiment, title: str) -> NewsItem:
    return NewsItem(
        source="test",
        category=NewsCategory.CRYPTO,
        title=title,
        url=f"https://example.com/{title}",
        sentiment=sentiment,
        sentiment_score=1.0,
    )


async def test_build_assembles_evidence_from_every_source():
    signal_engine = AsyncMock()
    signal_engine.get_latest.return_value = SignalSnapshot(
        bull_score=5,
        bear_score=0,
        net_score=5,
        confidence_pct=80,
        factors={
            "nasdaq_up": {"points": 2, "triggered": True},
            "vix_up": {"points": -3, "triggered": False},
        },
    )

    regime_detector = AsyncMock()
    regime_detector.get_latest.return_value = MarketRegimeSnapshot(
        regime=MarketRegime.RISK_ON, inputs={"btc_change_pct": 2.5}
    )

    news_repository = AsyncMock()
    news_repository.get_recent.return_value = [
        _news(NewsSentiment.BULLISH, "bull item"),
        _news(NewsSentiment.BEARISH, "bear item"),
    ]

    global_score_engine = AsyncMock()
    global_score_engine.get_latest.return_value = None

    scenario_engine = AsyncMock()
    scenario_engine.get_latest.return_value = ScenarioSnapshot(
        scenarios=[
            {"key": "soft_landing", "probability_pct": 60},
            {"key": "risk_off", "probability_pct": 40},
        ],
        global_score=55,
    )

    engine = _StubExplanationEngine(
        session_factory=None,
        signal_engine=signal_engine,
        regime_detector=regime_detector,
        news_repository=news_repository,
        global_score_engine=global_score_engine,
        scenario_engine=scenario_engine,
    )

    result = await engine.build("BTC")

    assert result["indicators"] == [{"name": "nasdaq_up", "points": 2, "triggered": True}]
    assert result["macro_drivers"] == {"btc_change_pct": 2.5}
    # net_score > 0 -> only bullish news kept
    assert [n["title"] for n in result["supporting_news"]] == ["bull item"]
    assert result["risk_factors"] is None
    assert result["alternative_view"]["key"] == "risk_off"


def test_condense_explanation_returns_none_for_empty_evidence():
    assert condense_explanation(None) is None
    assert condense_explanation({}) is None
    empty_evidence = {"indicators": [], "historical_examples": [], "supporting_news": []}
    assert condense_explanation(empty_evidence) is None


def test_condense_explanation_joins_available_parts():
    evidence = {
        "indicators": [
            {"name": "nasdaq_up", "triggered": True},
            {"name": "vix_up", "triggered": True},
        ],
        "historical_examples": [{"similarity_score": 80.0}],
        "supporting_news": [{"title": "a"}, {"title": "b"}],
    }

    result = condense_explanation(evidence)

    assert result == (
        "Why: Triggered: nasdaq up, vix up | 1 similar setup (avg 80% similar) "
        "| 2 supporting news items"
    )


def test_condense_explanation_partial_evidence_omits_missing_parts():
    evidence = {"indicators": [], "historical_examples": [], "supporting_news": [{"title": "a"}]}

    result = condense_explanation(evidence)

    assert result == "Why: 1 supporting news item"
