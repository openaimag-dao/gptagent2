from fastapi import APIRouter
from sqlalchemy import select

from app.database.models import HistoricalEvent
from app.database.session import get_session_factory

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
