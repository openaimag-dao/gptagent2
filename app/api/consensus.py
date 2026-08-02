from fastapi import APIRouter, HTTPException

from app.database.session import get_session_factory
from app.services.agents.orchestrator import build_agent_orchestrator
from app.services.consensus.engine import ConsensusEngine, consensus_evolution
from app.services.reliability.engine import AgentReliabilityEngine
from app.services.replay.engine import get_latest_consensus

router = APIRouter(prefix="/api/consensus", tags=["consensus"])


@router.get("")
async def get_consensus() -> dict:
    session_factory = get_session_factory()
    engine = ConsensusEngine(build_agent_orchestrator(), AgentReliabilityEngine(session_factory))
    result = await engine.compute()
    if result is None:
        raise HTTPException(
            status_code=503,
            detail="No agent reported a direction this cycle -- nothing to tally yet",
        )
    data = result.to_dict()
    previous_consensus = await get_latest_consensus(session_factory)
    data["confidence_evolution"] = consensus_evolution(previous_consensus, data)
    return data
