from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.database.models import HistoricalEvent
from app.database.session import get_session_factory
from app.services.history.schemas import Timeframe
from app.services.research.impact import EventImpactEngine

router = APIRouter(prefix="/api/events", tags=["history"])


@router.get("")
async def get_events() -> dict:
    async with get_session_factory()() as session:
        rows = list(
            await session.scalars(select(HistoricalEvent).order_by(HistoricalEvent.event_date))
        )

    return {
        "count": len(rows),
        "events": [
            {
                "event_date": row.event_date.isoformat(),
                "title": row.title,
                "category": row.category.value,
                "description": row.description,
                "symbols_affected": row.symbols_affected,
                "source": row.source,
            }
            for row in rows
        ],
    }


@router.get("/impact")
async def get_event_impact(
    category: str = Query(..., description="cpi, ppi, nfp, gdp, fomc, halving, crash, ..."),
    symbol: str = Query(..., description="Target symbol, e.g. BTC"),
    timeframe: str = Query("1d"),
) -> dict:
    try:
        tf = Timeframe(timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {timeframe}") from exc

    engine = EventImpactEngine(get_session_factory())
    results = await engine.measure_impact(category, symbol, timeframe=tf)
    if not results:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No impact data for {symbol.upper()} around {category} events "
                "(unknown category, no recorded events, or no history for this symbol)"
            ),
        )
    return {"symbol": symbol.upper(), "category": category.lower(), "events": results}
