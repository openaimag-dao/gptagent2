from fastapi import APIRouter, Query

from app.services.whales.engine import WhaleIntelligenceEngine

router = APIRouter(prefix="/api/whales", tags=["brain"])


@router.get("")
async def get_whale_snapshot(symbol: str = Query("BTC")) -> dict:
    engine = WhaleIntelligenceEngine()
    return await engine.get_snapshot(symbol)
