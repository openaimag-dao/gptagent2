from fastapi import APIRouter, HTTPException, Query

from app.database.session import get_session_factory
from app.services.history.schemas import Timeframe
from app.services.research.engine import ResearchEngine
from app.services.research.researcher import AIResearcherEngine

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


@router.get("/notes/latest")
async def get_latest_research_note() -> dict:
    engine = AIResearcherEngine(get_session_factory())
    note = await engine.get_latest()
    if note is None:
        raise HTTPException(status_code=404, detail="No research note generated yet")
    return {
        "note": note.note,
        "discoveries": note.discoveries,
        "discovery_count": note.discovery_count,
        "generated_at": note.generated_at.isoformat(),
    }


@router.post("/notes/generate")
async def generate_research_note(window_hours: int = Query(24, ge=1, le=168)) -> dict:
    engine = AIResearcherEngine(get_session_factory())
    note = await engine.generate_daily_note(window_hours=window_hours)
    return {
        "note": note.note,
        "discoveries": note.discoveries,
        "discovery_count": note.discovery_count,
        "generated_at": note.generated_at.isoformat(),
    }
