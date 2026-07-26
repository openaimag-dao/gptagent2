from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.database.session import get_session_factory
from app.services.hypothesis.engine import HypothesisEngine
from app.services.hypothesis.templates import HypothesisTemplate

router = APIRouter(prefix="/api/hypothesis", tags=["research"])


def _serialize(row) -> dict:
    return {
        "id": row.id,
        "statement": row.statement,
        "symbol": row.symbol,
        "event_a": row.event_a,
        "event_b": row.event_b,
        "verdict": row.verdict.value,
        "reason": row.reason,
        "result_a": row.result_a,
        "result_b": row.result_b,
        "tested_at": row.tested_at.isoformat(),
    }


@router.get("")
async def get_hypotheses(limit: int = Query(50, ge=1, le=200)) -> dict:
    engine = HypothesisEngine(get_session_factory())
    rows = await engine.get_latest(limit)
    return {"count": len(rows), "hypotheses": [_serialize(r) for r in rows]}


class HypothesisRequest(BaseModel):
    symbol: str
    event_a: str
    event_b: str


@router.post("/test")
async def test_hypothesis(request: HypothesisRequest) -> dict:
    engine = HypothesisEngine(get_session_factory())
    hypothesis = HypothesisTemplate(
        symbol=request.symbol.upper(),
        event_a=request.event_a.lower(),
        event_b=request.event_b.lower(),
    )
    row = await engine.test(hypothesis)
    return _serialize(row)


@router.post("/test-all")
async def test_all_hypotheses() -> dict:
    engine = HypothesisEngine(get_session_factory())
    rows = await engine.test_all()
    return {"count": len(rows), "hypotheses": [_serialize(r) for r in rows]}
