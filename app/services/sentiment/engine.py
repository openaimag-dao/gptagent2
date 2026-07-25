"""Sentiment Agent / Engine.

Combines every sentiment signal this project can actually source for real:
- Crypto Fear & Greed Index (alternative.me, real, no key required).
- News sentiment (the classified `NewsItem.sentiment` feed already collected
  by the News Engine), reduced to a 0-100 bullish/bearish balance.

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

from app.database.models import NewsItem, NewsSentiment, SentimentSnapshot
from app.services.common.scoring import center_scaled, weighted_average
from app.services.news.repository import NewsRepository
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
    bullish = sum(1 for i in items if i.sentiment == NewsSentiment.BULLISH)
    bearish = sum(1 for i in items if i.sentiment == NewsSentiment.BEARISH)
    net_fraction = (bullish - bearish) / len(items)
    return center_scaled(net_fraction, scale=50.0)


def compute_global_sentiment(components: dict[str, float | None]) -> int | None:
    result = weighted_average(components, _COMPONENT_WEIGHTS)
    return round(result) if result is not None else None


class SentimentEngine:
    """Computes and persists the Sentiment snapshot."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        news_repository: NewsRepository,
    ) -> None:
        self._session_factory = session_factory
        self._news_repository = news_repository

    async def compute_and_store(self) -> SentimentSnapshot:
        fear_greed = await fetch_fear_greed_index()
        since = datetime.now(UTC) - timedelta(hours=_NEWS_WINDOW_HOURS)
        news_items = await self._news_repository.get_recent(limit=100, since=since)
        news_score = _news_sentiment_score(news_items)

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
            news_items_analyzed=len(news_items),
            social_sentiment_available=False,
            social_sentiment_reason=_UNAVAILABLE_SOCIAL_REASON,
            global_sentiment_score=global_score,
        )
        async with self._session_factory() as session:
            session.add(snapshot)
            await session.commit()
            await session.refresh(snapshot)
        return snapshot

    async def get_latest(self) -> SentimentSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(SentimentSnapshot).order_by(SentimentSnapshot.computed_at.desc()).limit(1)
            )
