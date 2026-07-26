"""Shared event-date lookup -- used by both the Research Engine (Phase 3)
and the Event Impact Engine (Phase 6) so the category-to-table resolution
lives in exactly one place."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import (
    EconomicCalendarCategory,
    EconomicCalendarEvent,
    HistoricalEvent,
    HistoricalEventCategory,
)

CALENDAR_CATEGORIES = {c.value for c in EconomicCalendarCategory}
HISTORICAL_CATEGORIES = {c.value for c in HistoricalEventCategory}


async def get_event_dates(
    session_factory: async_sessionmaker[AsyncSession], event_category: str
) -> list:
    """Real event dates for a category from whichever table actually has
    it -- EconomicCalendarEvent (scheduled macro releases/meetings) or
    HistoricalEvent (curated one-off events). Empty list for an unknown
    category rather than raising, so callers can treat "no events" and
    "unknown category" the same way (both mean nothing to compute)."""
    category = event_category.lower()
    async with session_factory() as session:
        if category in CALENDAR_CATEGORIES:
            rows = await session.scalars(
                select(EconomicCalendarEvent.event_date)
                .where(EconomicCalendarEvent.category == category)
                .order_by(EconomicCalendarEvent.event_date)
            )
            return list(rows)
        if category in HISTORICAL_CATEGORIES:
            rows = await session.scalars(
                select(HistoricalEvent.event_date)
                .where(HistoricalEvent.category == category)
                .order_by(HistoricalEvent.event_date)
            )
            return list(rows)
    return []
