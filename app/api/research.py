from fastapi import APIRouter, HTTPException, Query

from app.database.session import get_session_factory
from app.services.history.schemas import Timeframe
from app.services.research.engine import ResearchEngine

router = APIRouter(prefix="/api/research", tags=["research"])


@router.get("")
async def get_research(
    symbol: str = Query(..., description="Target symbol, e.g. BTC"),
    event: str = Query(..., description="cpi, ppi, nfp, gdp, fomc, halving, crash, ..."),
    horizon: int = Query(1, ge=1, le=90),
    timeframe: str = Query("1d"),
) -> dict:
    try:
        tf = Timeframe(timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {timeframe}") from exc

    engine = ResearchEngine(get_session_factory())
    result = await engine.test_hypothesis(symbol, event, timeframe=tf, horizon=horizon)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No usable result for {symbol.upper()} after {event} "
                f"(unknown category, no recorded events, or no history for {symbol.upper()})"
            ),
        )
    return result
