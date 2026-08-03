from fastapi import APIRouter

from app.services.explainability.engine import build_explainability_engine

router = APIRouter(prefix="/api/explanation", tags=["explanation"])


@router.get("/{symbol}")
async def get_explanation(symbol: str = "BTC") -> dict:
    engine = build_explainability_engine()
    return await engine.build(symbol)
