from fastapi import APIRouter

from app.database.session import get_session_factory
from app.services.news.repository import NewsRepository
from app.services.sentiment.engine import SentimentEngine

router = APIRouter(prefix="/api/sentiment", tags=["sentiment"])


def _build_engine() -> SentimentEngine:
    session_factory = get_session_factory()
    return SentimentEngine(session_factory, NewsRepository(session_factory))


def _serialize(row) -> dict:
    return {
        "fear_greed_value": row.fear_greed_value,
        "fear_greed_classification": row.fear_greed_classification,
        "news_sentiment_score": row.news_sentiment_score,
        "news_items_analyzed": row.news_items_analyzed,
        "social_sentiment_available": row.social_sentiment_available,
        "social_sentiment_reason": row.social_sentiment_reason,
        "global_sentiment_score": row.global_sentiment_score,
        "computed_at": row.computed_at.isoformat(),
    }


@router.get("")
async def get_sentiment() -> dict:
    engine = _build_engine()
    row = await engine.compute_and_store()
    return _serialize(row)
