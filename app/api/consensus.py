from fastapi import APIRouter, HTTPException

from app.database.session import get_session_factory
from app.services.agents.orchestrator import build_agent_orchestrator
from app.services.consensus.engine import ConsensusEngine
from app.services.reliability.engine import AgentReliabilityEngine

router = APIRouter(prefix="/api/consensus", tags=["consensus"])


@router.get("")
async def get_consensus() -> dict:
    engine = ConsensusEngine(
        build_agent_orchestrator(), AgentReliabilityEngine(get_session_factory())
    )
    result = await engine.compute()
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="No agent reported a direction this cycle -- nothing to tally yet",
        )
    return result.to_dict()
