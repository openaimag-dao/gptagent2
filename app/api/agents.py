from fastapi import APIRouter

from app.services.agents.orchestrator import build_agent_orchestrator

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
async def get_agent_outputs() -> dict:
    orchestrator = build_agent_orchestrator()
    outputs = await orchestrator.run_all()
    return {name: output.to_dict() for name, output in outputs.items()}
