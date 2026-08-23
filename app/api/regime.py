from fastapi import APIRouter, HTTPException

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.analysis.regime import RegimeDetector, describe_regime, regime_confidence_label
from app.services.market.repository import MarketRepository

router = APIRouter(prefix="/api/regime", tags=["regime"])


@router.get("")
async def get_latest_regime() -> dict:
    market_repository = MarketRepository(get_session_factory(), get_redis())
    detector = RegimeDetector(get_session_factory(), market_repository)
    snapshot = await detector.get_latest()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="No regime has been computed yet")
    streak = await detector.get_regime_streak()

    return {
        "regime": snapshot.regime.value,
        "inputs": snapshot.inputs,
        "confidence_pct": snapshot.confidence_pct,
        "confidence_label": regime_confidence_label(snapshot.confidence_pct),
        "explanation": describe_regime(snapshot.regime.value, snapshot.inputs),
        "since": streak["since"].isoformat() if streak else None,
        "duration_hours": streak["duration_hours"] if streak else None,
        "duration_is_lower_bound": streak["duration_is_lower_bound"] if streak else False,
        "computed_at": snapshot.computed_at.isoformat(),
    }
