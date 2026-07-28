from fastapi import APIRouter

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.analysis.regime import RegimeDetector
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.signals.engine import SignalEngine

router = APIRouter(prefix="/api/status", tags=["status"])


@router.get("")
async def get_status() -> dict:
    """Last-computed timestamps for the core engines, so staleness is
    visible rather than guessed -- same data /status in Telegram reports."""
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )

    signal_snapshot = await signal_engine.get_latest()
    regime_snapshot = await regime_detector.get_latest()
    global_score = await global_score_engine.get_latest()

    return {
        "signal_computed_at": (
            signal_snapshot.computed_at.isoformat() if signal_snapshot is not None else None
        ),
        "regime_computed_at": (
            regime_snapshot.computed_at.isoformat() if regime_snapshot is not None else None
        ),
        "global_score_computed_at": (
            global_score.computed_at.isoformat() if global_score is not None else None
        ),
    }
