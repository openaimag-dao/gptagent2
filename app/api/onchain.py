from fastapi import APIRouter

from app.services.onchain.engine import OnChainIntelligenceEngine

router = APIRouter(prefix="/api/onchain", tags=["brain"])


@router.get("/{symbol}")
async def get_onchain_snapshot(symbol: str) -> dict:
    engine = OnChainIntelligenceEngine()
    return await engine.get_snapshot(symbol)
