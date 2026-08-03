from fastapi import APIRouter, Query

from app.services.accuracy.engine import build_accuracy_engine

router = APIRouter(prefix="/api/accuracy", tags=["accuracy"])


@router.get("")
async def get_accuracy(symbol: str | None = Query(None)) -> dict:
    engine = build_accuracy_engine()
    return await engine.compute(symbol)
