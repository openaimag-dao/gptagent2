import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import NewsItem
from app.services.news.schemas import ClassifiedNewsItem

logger = logging.getLogger(__name__)


class NewsRepository:
    """Persists classified news items, de-duplicated by URL."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def save_new_items(self, items: list[ClassifiedNewsItem]) -> int:
        """Inserts items whose URL isn't already stored. Returns the count actually inserted."""
        if not items:
            return 0

        async with self._session_factory() as session:
            stmt = (
                pg_insert(NewsItem)
                .values(
                    [
                        {
                            "source": item.source,
                            "category": item.category,
                            "title": item.title,
                            "url": item.url,
                            "summary": item.summary,
                            "sentiment": item.sentiment,
                            "sentiment_score": item.sentiment_score,
                            "published_at": item.published_at,
                        }
                        for item in items
                    ]
                )
                .on_conflict_do_nothing(index_elements=["url"])
                .returning(NewsItem.id)
            )
            result = await session.execute(stmt)
            inserted = len(result.fetchall())
            await session.commit()
            return inserted

    async def get_recent(self, category: str | None = None, limit: int = 50) -> list[NewsItem]:
        async with self._session_factory() as session:
            query = (
                select(NewsItem)
                .order_by(NewsItem.published_at.desc().nullslast(), NewsItem.fetched_at.desc())
                .limit(limit)
            )
            if category is not None:
                query = query.where(NewsItem.category == category)
            result = await session.scalars(query)
            return list(result)
