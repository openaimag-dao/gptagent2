from fastapi import APIRouter, Query

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.conviction.engine import ConvictionEngine
from app.services.history.schemas import Timeframe
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.probability.engine import ProbabilityEngine
from app.services.signals.engine import SignalEngine

router = APIRouter(prefix="/api/conviction", tags=["conviction"])


def _build_engine() -> ConvictionEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    signal_engine = SignalEngine(
        session_factory, market_repository, NewsRepository(session_factory)
    )
    probability_engine = ProbabilityEngine(session_factory)
    return ConvictionEngine(signal_engine, probability_engine)


@router.get("")
async def get_conviction(symbol: str = Query("BTC")) -> dict:
    engine = _build_engine()
    signal_conviction = await engine.evaluate_signal()
    probability_conviction = await engine.evaluate_probability(symbol.upper(), Timeframe.DAILY)
    return {
        "signal": signal_conviction,
        "probability": {"symbol": symbol.upper(), **probability_conviction}
        if probability_conviction is not None
        else None,
    }
