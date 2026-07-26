from fastapi import APIRouter, HTTPException

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.analysis.regime import RegimeDetector
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.signals.engine import SignalEngine

router = APIRouter(prefix="/api/liquidity", tags=["liquidity"])


def _build_engine() -> GlobalScoreEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(
        session_factory, market_repository, NewsRepository(session_factory)
    )
    return GlobalScoreEngine(session_factory, market_repository, regime_detector, signal_engine)


@router.get("")
async def get_liquidity() -> dict:
    """A focused read of the Global Market Score's liquidity/macro-pressure
    sub-scores -- not a second computation, the same GlobalScoreEngine."""
    engine = _build_engine()
    row = await engine.compute_and_store()
    if row is None:
        raise HTTPException(
            status_code=503,
            detail="Cannot compute liquidity before regime detection and signal scoring "
            "have run at least once",
        )
    return {
        "liquidity_score": row.liquidity_score,
        "macro_pressure_score": row.macro_pressure_score,
        "risk_on_score": row.risk_on_score,
        "risk_off_score": row.risk_off_score,
        "inputs": {
            k: row.inputs.get(k) for k in ("fedrate_change", "dxy_change_pct", "us10y_change")
        },
        "computed_at": row.computed_at.isoformat(),
    }
