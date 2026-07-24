from fastapi import APIRouter, HTTPException

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.analysis.regime import RegimeDetector
from app.services.market.repository import MarketRepository

router = APIRouter(prefix="/api/regime", tags=["regime"])


@router.get("")
async def get_latest_regime() -> dict:
    market_repository = MarketRepository(get_session_factory(), get_redis())
    detector = RegimeDetector(get_session_factory(), market_repository)
    snapshot = await detector.get_latest()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No regime has been computed yet")

    return {
        "regime": snapshot.regime.value,
        "inputs": snapshot.inputs,
        "computed_at": snapshot.computed_at.isoformat(),
    }
