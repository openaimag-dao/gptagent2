from fastapi import APIRouter, HTTPException

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.agents.orchestrator import build_agent_orchestrator
from app.services.analysis.regime import RegimeDetector
from app.services.committee.engine import CommitteeEngine
from app.services.market.repository import MarketRepository
from app.services.reliability.engine import AgentReliabilityEngine

router = APIRouter(prefix="/api/committee", tags=["brain"])


@router.get("")
async def get_committee_verdict() -> dict:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    engine = CommitteeEngine(
        build_agent_orchestrator(),
        AgentReliabilityEngine(session_factory),
        RegimeDetector(session_factory, market_repository),
    )
    verdict = await engine.convene()
    if verdict is None:
        raise HTTPException(status_code=503, detail="No agent has reported a direction yet.")
    return verdict.to_dict()
