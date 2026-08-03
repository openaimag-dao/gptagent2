from fastapi import APIRouter, HTTPException

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.analysis.regime import RegimeDetector
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.scenarios.engine import ScenarioEngine, scenario_extremes, scenario_threat_level
from app.services.signals.engine import SignalEngine

router = APIRouter(prefix="/api/scenarios", tags=["scenarios"])


def _build_engine() -> ScenarioEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(
        session_factory, market_repository, NewsRepository(session_factory)
    )
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    return ScenarioEngine(session_factory, global_score_engine)


@router.get("")
async def get_scenarios() -> dict:
    engine = _build_engine()
    row = await engine.compute_and_store()
    if row is None:
        raise HTTPException(
            status_code=503,
            detail="Cannot compute scenarios before regime detection and signal scoring "
            "have run at least once",
        )
    _, _, highest_risk, biggest_opportunity = scenario_extremes(row.scenarios)
    return {
        "scenarios": row.scenarios,
        "global_score": row.global_score,
        "computed_at": row.computed_at.isoformat(),
        "threat_level": scenario_threat_level(row.scenarios),
        "highest_risk": highest_risk,
        "biggest_opportunity": biggest_opportunity,
    }
