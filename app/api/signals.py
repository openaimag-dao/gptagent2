from fastapi import APIRouter, HTTPException

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.signals.engine import SignalEngine

router = APIRouter(prefix="/api/signals", tags=["signals"])


@router.get("")
async def get_latest_signal() -> dict:
    market_repository = MarketRepository(get_session_factory(), get_redis())
    news_repository = NewsRepository(get_session_factory())
    engine = SignalEngine(get_session_factory(), market_repository, news_repository)

    snapshot = await engine.get_latest()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No signal has been computed yet")

    return {
        "bull_score": snapshot.bull_score,
        "bear_score": snapshot.bear_score,
        "net_score": snapshot.net_score,
        "confidence_pct": snapshot.confidence_pct,
        "factors": snapshot.factors,
        "computed_at": snapshot.computed_at.isoformat(),
    }
