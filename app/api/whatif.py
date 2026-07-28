from fastapi import APIRouter, HTTPException

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.analysis.correlation import CorrelationEngine
from app.services.analysis.regime import RegimeDetector
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.probability.engine import ProbabilityEngine
from app.services.research.impact import EventImpactEngine
from app.services.signals.engine import SignalEngine
from app.services.whatif.engine import WhatIfSimulator

router = APIRouter(prefix="/api/whatif", tags=["scenarios"])


def _build_simulator() -> WhatIfSimulator:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(
        session_factory, market_repository, NewsRepository(session_factory)
    )
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    return WhatIfSimulator(
        EventImpactEngine(session_factory),
        CorrelationEngine(session_factory),
        regime_detector,
        global_score_engine,
        ProbabilityEngine(session_factory),
    )


@router.get("")
async def list_whatif_scenarios() -> dict:
    return {"scenarios": _build_simulator().list_scenarios()}


@router.get("/{scenario_key}")
async def simulate_whatif_scenario(scenario_key: str) -> dict:
    result = await _build_simulator().simulate(scenario_key)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Unknown scenario: {scenario_key}")
    return result
