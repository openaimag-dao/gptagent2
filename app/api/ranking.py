from fastapi import APIRouter, HTTPException, Query

from app.database.session import get_session_factory
from app.services.ranking.engine import RankingEngine

router = APIRouter(prefix="/api/ranking", tags=["research"])


@router.get("")
async def get_ranking(
    symbol: str = Query("BTC", description="Target symbol rankings are measured against"),
    compute: bool = Query(False, description="Recompute now instead of using the latest stored"),
) -> dict:
    engine = RankingEngine(get_session_factory())
    row = await engine.compute_and_store(symbol) if compute else await engine.get_latest(symbol)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No ranking computed yet for {symbol.upper()}")
    return {
        "target_symbol": row.target_symbol,
        "rankings": row.rankings,
        "computed_at": row.computed_at.isoformat(),
    }
