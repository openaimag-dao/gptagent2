from fastapi import APIRouter, Query

from app.database.session import get_session_factory
from app.services.news.repository import NewsRepository
from app.services.news.schemas import NewsCategory

router = APIRouter(prefix="/api/news", tags=["news"])


def _get_repository() -> NewsRepository:
    return NewsRepository(get_session_factory())


@router.get("")
async def get_recent_news(
    category: NewsCategory | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    repository = _get_repository()
    items = await repository.get_recent(
        category=category.value if category is not None else None, limit=limit
    )

    return {
        "count": len(items),
        "items": [
            {
                "source": item.source,
                "category": item.category.value,
                "title": item.title,
                "url": item.url,
                "summary": item.summary,
                "sentiment": item.sentiment.value,
                "sentiment_score": float(item.sentiment_score),
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "fetched_at": item.fetched_at.isoformat(),
            }
            for item in items
        ],
    }
