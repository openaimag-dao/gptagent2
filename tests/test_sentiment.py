from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.database.models import NewsCategory, NewsItem, NewsSentiment
from app.services.sentiment.engine import (
    SentimentEngine,
    _alphavantage_news_score,
    _news_sentiment_score,
    compute_global_sentiment,
)


def _news(sentiment: NewsSentiment) -> NewsItem:
    return NewsItem(
        source="test",
        category=NewsCategory.CRYPTO,
        title="t",
        url=f"https://example.com/{id(object())}",
        sentiment=sentiment,
        sentiment_score=0,
    )


def test_news_sentiment_score_none_when_no_items():
    assert _news_sentiment_score([]) is None


def test_news_sentiment_score_all_bullish_is_high():
    items = [_news(NewsSentiment.BULLISH) for _ in range(5)]
    assert _news_sentiment_score(items) == 100


def test_news_sentiment_score_all_bearish_is_low():
    items = [_news(NewsSentiment.BEARISH) for _ in range(5)]
    assert _news_sentiment_score(items) == 0


def test_news_sentiment_score_mixed_is_centered():
    items = [_news(NewsSentiment.BULLISH), _news(NewsSentiment.BEARISH)]
    assert _news_sentiment_score(items) == 50


def test_global_sentiment_none_when_nothing_available():
    assert compute_global_sentiment({"fear_greed": None, "news_sentiment": None}) is None


def test_global_sentiment_uses_only_available_components():
    only_news = compute_global_sentiment({"fear_greed": None, "news_sentiment": 80.0})
    assert only_news == 80

    only_fear_greed = compute_global_sentiment({"fear_greed": 20.0, "news_sentiment": None})
    assert only_fear_greed == 20


def test_global_sentiment_weighted_average_when_both_available():
    result = compute_global_sentiment({"fear_greed": 60.0, "news_sentiment": 60.0})
    assert result == 60


def test_alphavantage_news_score_none_when_no_items():
    assert _alphavantage_news_score([]) is None


def test_alphavantage_news_score_bullish_average():
    items = [{"sentiment_score": 0.5}, {"sentiment_score": 0.3}]
    assert _alphavantage_news_score(items) == 70


def test_alphavantage_news_score_bearish_average():
    items = [{"sentiment_score": -0.4}]
    assert _alphavantage_news_score(items) == 30


async def test_get_latest_bounds_the_query_when_as_of_is_given():
    # Forecasting 2.0 (Part 41): a forecast's own reference_timestamp must
    # bound the sentiment read so nothing published after the fact can
    # leak in -- without this, get_latest() always reads whatever's newest
    # in the DB at wall-clock call time regardless of `as_of`.
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.__aenter__.return_value = session
    session_factory = MagicMock(return_value=session)
    engine = SentimentEngine(session_factory, news_repository=MagicMock())

    cutoff = datetime(2026, 8, 1, tzinfo=UTC)
    await engine.get_latest(as_of=cutoff)

    query = session.scalar.call_args[0][0]
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "computed_at <=" in compiled
    assert "2026-08-01" in compiled


async def test_get_latest_unbounded_when_as_of_is_none():
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.__aenter__.return_value = session
    session_factory = MagicMock(return_value=session)
    engine = SentimentEngine(session_factory, news_repository=MagicMock())

    await engine.get_latest()

    query = session.scalar.call_args[0][0]
    compiled = str(query.compile())
    assert "computed_at <=" not in compiled
