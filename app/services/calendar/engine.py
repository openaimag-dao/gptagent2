"""Economic Calendar Engine: syncs real FRED release dates (CPI/PPI/NFP/GDP)
and the curated FOMC seed into EconomicCalendarEvent, and serves recent/
upcoming queries used by the Event Impact Engine (Phase 6) and Telegram."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import EconomicCalendarEvent
from app.services.calendar.fred_releases import (
    FRED_CALENDAR_RELEASES,
    FredCalendarError,
    FredReleaseCalendarClient,
    to_event_datetime,
)
from app.services.calendar.seed import SEED_CENTRAL_BANK_MEETINGS

logger = logging.getLogger(__name__)


class EconomicCalendarEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        fred_client: FredReleaseCalendarClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._fred_client = fred_client or FredReleaseCalendarClient()

    async def _upsert(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        async with self._session_factory() as session:
            stmt = pg_insert(EconomicCalendarEvent).values(rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=["category", "country", "event_date"])
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount or 0

    async def sync_fred_releases(self) -> int:
        """Pulls real release dates from FRED for CPI/PPI/NFP/GDP. One
        release_id failing (bad key, rate limit, wrong id) never blocks the
        others -- matches this project's fault-tolerant sync pattern."""
        if not self._fred_client.configured:
            logger.info("Economic calendar: FRED_API_KEY not configured, skipping FRED sync")
            return 0

        total = 0
        for category, (release_id, importance) in FRED_CALENDAR_RELEASES.items():
            try:
                dates = await self._fred_client.fetch_release_dates(release_id)
            except FredCalendarError as exc:
                logger.warning("Economic calendar: FRED sync failed for %s: %s", category, exc)
                continue
            rows = [
                {
                    "event_date": to_event_datetime(day),
                    "category": category.value,
                    "country": "US",
                    "title": f"{category.value.upper()} Release",
                    "importance": importance,
                    "source": "fred_release_dates",
                }
                for day in dates
            ]
            total += await self._upsert(rows)
        return total

    async def seed_central_bank_meetings(self) -> int:
        rows = [
            {**event, "category": event["category"].value} for event in SEED_CENTRAL_BANK_MEETINGS
        ]
        return await self._upsert(rows)

    async def get_recent(self, days_back: int = 30) -> list[EconomicCalendarEvent]:
        since = datetime.now(UTC) - timedelta(days=days_back)
        async with self._session_factory() as session:
            return list(
                await session.scalars(
                    select(EconomicCalendarEvent)
                    .where(
                        EconomicCalendarEvent.event_date >= since,
                        EconomicCalendarEvent.event_date <= datetime.now(UTC),
                    )
                    .order_by(EconomicCalendarEvent.event_date.desc())
                )
            )

    async def get_upcoming(self, days_ahead: int = 30) -> list[EconomicCalendarEvent]:
        now = datetime.now(UTC)
        horizon = now + timedelta(days=days_ahead)
        async with self._session_factory() as session:
            return list(
                await session.scalars(
                    select(EconomicCalendarEvent)
                    .where(
                        EconomicCalendarEvent.event_date > now,
                        EconomicCalendarEvent.event_date <= horizon,
                    )
                    .order_by(EconomicCalendarEvent.event_date.asc())
                )
            )
