from fastapi import APIRouter, Query

from app.database.session import get_session_factory
from app.services.calendar.engine import EconomicCalendarEngine

router = APIRouter(prefix="/api/calendar", tags=["history"])


def _serialize(row) -> dict:
    return {
        "event_date": row.event_date.isoformat(),
        "category": row.category.value,
        "country": row.country,
        "title": row.title,
        "importance": row.importance,
        "source": row.source,
    }


@router.get("")
async def get_calendar(
    days_back: int = Query(30, ge=0, le=365),
    days_ahead: int = Query(30, ge=0, le=365),
) -> dict:
    engine = EconomicCalendarEngine(get_session_factory())
    recent = await engine.get_recent(days_back)
    upcoming = await engine.get_upcoming(days_ahead)
    return {
        "recent": [_serialize(row) for row in recent],
        "upcoming": [_serialize(row) for row in upcoming],
    }
