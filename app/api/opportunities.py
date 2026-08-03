from fastapi import APIRouter, Query

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.scheduler.jobs import FEATURE_SYMBOLS
from app.services.analysis.regime import RegimeDetector
from app.services.breakout.engine import BreakoutEngine
from app.services.features.engine import FeatureEngine
from app.services.history.schemas import Timeframe
from app.services.market.repository import MarketRepository
from app.services.opportunities.engine import rank_opportunities

router = APIRouter(prefix="/api/opportunities", tags=["opportunities"])


def _build_engine() -> BreakoutEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    return BreakoutEngine(
        session_factory,
        RegimeDetector(session_factory, market_repository),
        FeatureEngine(session_factory, market_repository),
    )


@router.get("")
async def get_opportunities(limit: int = Query(10, ge=1, le=len(FEATURE_SYMBOLS))) -> dict:
    engine = _build_engine()
    events = await engine.get_latest_across(FEATURE_SYMBOLS, Timeframe.DAILY)
    opportunities = rank_opportunities(events, limit=limit)
    return {"count": len(opportunities), "opportunities": opportunities}
