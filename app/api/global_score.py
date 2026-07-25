from fastapi import APIRouter, HTTPException

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.analysis.regime import RegimeDetector
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.signals.engine import SignalEngine

router = APIRouter(prefix="/api/global-score", tags=["brain"])


def _build_engine() -> GlobalScoreEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    return GlobalScoreEngine(
        session_factory,
        market_repository,
        RegimeDetector(session_factory, market_repository),
        SignalEngine(session_factory, market_repository, NewsRepository(session_factory)),
    )


@router.get("")
async def get_global_score() -> dict:
    engine = _build_engine()
    row = await engine.compute_and_store()
    if row is None:
        raise HTTPException(
            status_code=503,
            detail="Cannot compute a global score before regime detection and signal "
            "scoring have run at least once",
        )
    return {
        "risk_on_score": row.risk_on_score,
        "risk_off_score": row.risk_off_score,
        "liquidity_score": row.liquidity_score,
        "fear_score": row.fear_score,
        "greed_score": row.greed_score,
        "macro_pressure_score": row.macro_pressure_score,
        "institutional_activity_score": row.institutional_activity_score,
        "crypto_strength_score": row.crypto_strength_score,
        "stock_strength_score": row.stock_strength_score,
        "global_score": row.global_score,
        "computed_at": row.computed_at.isoformat(),
    }
