"""A small, curated seed of well-documented FOMC meeting dates.

Same principle as app/services/history/events.py's HistoricalEvent seed:
hand-written from well-documented public record, not fetched or invented --
a starting seed, not an exhaustive or forward-looking calendar. ECB/BOJ/PBOC
meeting dates aren't seeded yet (no verified source wired up here); extend
SEED_CENTRAL_BANK_MEETINGS as needed rather than guessing dates.

Event date is the second (decision/announcement) day of each two-day
meeting, since that's when the market-moving news actually lands.
"""

from datetime import UTC, datetime

from app.database.models import EconomicCalendarCategory

SEED_CENTRAL_BANK_MEETINGS: list[dict] = [
    {
        "event_date": datetime(2024, 1, 31, tzinfo=UTC),
        "category": EconomicCalendarCategory.FOMC,
        "country": "US",
        "title": "FOMC Meeting (Jan 2024)",
        "importance": "high",
        "source": "manual_seed",
    },
    {
        "event_date": datetime(2024, 3, 20, tzinfo=UTC),
        "category": EconomicCalendarCategory.FOMC,
        "country": "US",
        "title": "FOMC Meeting (Mar 2024)",
        "importance": "high",
        "source": "manual_seed",
    },
    {
        "event_date": datetime(2024, 5, 1, tzinfo=UTC),
        "category": EconomicCalendarCategory.FOMC,
        "country": "US",
        "title": "FOMC Meeting (May 2024)",
        "importance": "high",
        "source": "manual_seed",
    },
    {
        "event_date": datetime(2024, 6, 12, tzinfo=UTC),
        "category": EconomicCalendarCategory.FOMC,
        "country": "US",
        "title": "FOMC Meeting (Jun 2024)",
        "importance": "high",
        "source": "manual_seed",
    },
    {
        "event_date": datetime(2024, 7, 31, tzinfo=UTC),
        "category": EconomicCalendarCategory.FOMC,
        "country": "US",
        "title": "FOMC Meeting (Jul 2024)",
        "importance": "high",
        "source": "manual_seed",
    },
    {
        "event_date": datetime(2024, 9, 18, tzinfo=UTC),
        "category": EconomicCalendarCategory.FOMC,
        "country": "US",
        "title": "FOMC Meeting (Sep 2024)",
        "importance": "high",
        "source": "manual_seed",
    },
    {
        "event_date": datetime(2024, 11, 7, tzinfo=UTC),
        "category": EconomicCalendarCategory.FOMC,
        "country": "US",
        "title": "FOMC Meeting (Nov 2024)",
        "importance": "high",
        "source": "manual_seed",
    },
    {
        "event_date": datetime(2024, 12, 18, tzinfo=UTC),
        "category": EconomicCalendarCategory.FOMC,
        "country": "US",
        "title": "FOMC Meeting (Dec 2024)",
        "importance": "high",
        "source": "manual_seed",
    },
]
