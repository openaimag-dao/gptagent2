"""Sentiment Agent / Engine.

Combines every sentiment signal this project can actually source for real:
- Crypto Fear & Greed Index (alternative.me, real, no key required).
- News sentiment: the classified `NewsItem.sentiment` feed already collected
  by the RSS News Engine, reduced to a 0-100 bullish/bearish balance. If the
  RSS feed produced nothing in the window (dead sources, empty cycle), Alpha
  Vantage's NEWS_SENTIMENT API is tried as a fallback so a quiet RSS cycle
  doesn't silently zero out news sentiment -- which of the two produced the
  score is logged, not surfaced as a new field, so the briefing format is
  unchanged.

Twitter/X, Reddit and options-market sentiment have no configured or free
data source in this project, so they are reported as unavailable with a
clear reason -- never blended into `global_sentiment_score` as a guess.
`global_sentiment_score` is the weighted average of only the components
that are actually available, renormalized over their weights.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import NewsItem, SentimentSnapshot
from app.services.common.scoring import center_scaled, weighted_average
from app.services.market.providers.alphavantage import AlphaVantageClient
from app.services.news.repository import NewsRepository, count_by_sentiment
from app.services.sentiment.fear_greed import fetch_fear_greed_index

logger = logging.getLogger(__name__)

_NEWS_WINDOW_HOURS = 24
_UNAVAILABLE_SOCIAL_REASON = (
    "No Twitter/X, Reddit or options-market sentiment provider is configured -- "
    "these require paid social/derivatives data APIs this project doesn't have "
    "access to. Reported honestly as unavailable rather than guessed."
)

# component name -> weight, applied only over components actually available.
_COMPONENT_WEIGHTS: dict[str, float] = {
    "fear_greed": 0.6,
    "news_sentiment": 0.4,
}


def _news_sentiment_score(items: list[NewsItem]) -> float | None:
    if not items:
        return None
    bullish, bearish, _ = count_by_sentiment(items)
    net_fraction = (bullish - bearish) / len(items)
    return center_scaled(net_fraction, scale=50.0)


def _alphavantage_news_score(items: list[dict]) -> float | None:
    if not items:
        return None
    average = sum(item["sentiment_score"] for item in items) / len(items)
    return center_scaled(average, scale=50.0)


def compute_global_sentiment(components: dict[str, float | None]) -> int | None:
    result = weighted_average(components, _COMPONENT_WEIGHTS)
    return round(result) if result is not None else None


class SentimentEngine:
    """Computes and persists the Sentiment snapshot."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        news_repository: NewsRepository,
        alphavantage: AlphaVantageClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._news_repository = news_repository
        self._alphavantage = alphavantage or AlphaVantageClient()

    async def compute_and_store(self) -> SentimentSnapshot:
        fear_greed = await fetch_fear_greed_index()
        since = datetime.now(UTC) - timedelta(hours=_NEWS_WINDOW_HOURS)
        news_items = await self._news_repository.get_recent(limit=100, since=since)
        news_score = _news_sentiment_score(news_items)
        news_items_analyzed = len(news_items)
        news_source = "rss" if news_score is not None else None

        if news_score is None and self._alphavantage.configured:
            av_items = await self._alphavantage.get_news_sentiment()
            if av_items:
                news_score = _alphavantage_news_score(av_items)
                news_items_analyzed = len(av_items)
                news_source = "alphavantage"

        logger.info(
            "Sentiment components: fear_greed=%s news_sentiment=%s (source=%s)",
            "ok" if fear_greed is not None else "unavailable",
            "ok" if news_score is not None else "unavailable",
            news_source or "none",
        )

        components = {
            "fear_greed": float(fear_greed["value"]) if fear_greed is not None else None,
            "news_sentiment": news_score,
        }
        global_score = compute_global_sentiment(components)

        snapshot = SentimentSnapshot(
            fear_greed_value=fear_greed["value"] if fear_greed is not None else None,
            fear_greed_classification=(
                fear_greed["classification"] if fear_greed is not None else None
            ),
            news_sentiment_score=round(news_score) if news_score is not None else None,
            news_items_analyzed=news_items_analyzed,
            social_sentiment_available=False,
            social_sentiment_reason=_UNAVAILABLE_SOCIAL_REASON,
            global_sentiment_score=global_score,
        )
        async with self._session_factory() as session:
            session.add(snapshot)
            await session.commit()
            await session.refresh(snapshot)
        return snapshot

    async def get_latest(self, as_of: datetime | None = None) -> SentimentSnapshot | None:
        """`as_of` bounds this read to what was actually knowable at that
        moment (e.g. a forecast's own reference_timestamp) -- Forecasting
        2.0 needs this so a daily forecast's snapshot can never be
        contaminated by sentiment computed after the fact. `None` (the
        default) keeps every other caller's existing "give me the current
        read" behavior unchanged."""
        async with self._session_factory() as session:
            query = select(SentimentSnapshot).order_by(SentimentSnapshot.computed_at.desc())
            if as_of is not None:
                query = query.where(SentimentSnapshot.computed_at <= as_of)
            return await session.scalar(query.limit(1))
