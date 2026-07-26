from fastapi import APIRouter, HTTPException, Query

from app.database.session import get_session_factory
from app.services.features.engine import FeatureEngine

router = APIRouter(prefix="/api/features", tags=["features"])


@router.get("/{symbol}")
async def get_features(symbol: str, compute: bool = Query(False)) -> dict:
    engine = FeatureEngine(get_session_factory())
    row = await engine.compute_and_store(symbol) if compute else await engine.get_latest(symbol)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No feature snapshot yet for {symbol.upper()}")
    return {
        "symbol": row.symbol,
        "features": row.features,
        "computed_at": row.computed_at.isoformat(),
    }
