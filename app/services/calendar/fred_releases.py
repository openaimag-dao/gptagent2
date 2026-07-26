"""FRED release-dates client -- real historical (and, when FRED itself
publishes them, upcoming) publication dates for CPI/PPI/NFP/GDP.

FRED's `/fred/release/dates` endpoint returns whatever dates FRED has on
record for a given release_id -- this provider stores exactly that, never
inferring or extrapolating a date FRED didn't return. Release IDs below are
FRED's well-known, stable catalog IDs for these releases; only reachability
(not a real key's actual data) could be confirmed while building this --
verify with a real FRED_API_KEY (already required elsewhere in this
project) if a release_id looks wrong.
"""

import logging
from datetime import UTC, date, datetime

import httpx

from app.config import get_settings
from app.database.models import EconomicCalendarCategory
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

FRED_RELEASE_DATES_URL = "https://api.stlouisfed.org/fred/release/dates"

# category -> (FRED release_id, importance)
FRED_CALENDAR_RELEASES: dict[EconomicCalendarCategory, tuple[int, str]] = {
    EconomicCalendarCategory.CPI: (10, "high"),
    EconomicCalendarCategory.PPI: (46, "medium"),
    EconomicCalendarCategory.NFP: (50, "high"),
    EconomicCalendarCategory.GDP: (53, "high"),
}


class FredCalendarError(RuntimeError):
    pass


class FredReleaseCalendarClient:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def configured(self) -> bool:
        return bool(self._settings.fred_api_key)

    @default_retry()
    async def _get(self, client: httpx.AsyncClient, release_id: int) -> dict:
        response = await client.get(
            FRED_RELEASE_DATES_URL,
            params={
                "release_id": release_id,
                "api_key": self._settings.fred_api_key,
                "file_type": "json",
                "sort_order": "asc",
                "limit": 1000,
            },
        )
        response.raise_for_status()
        return response.json()

    async def fetch_release_dates(self, release_id: int) -> list[date]:
        if not self.configured:
            raise FredCalendarError("FRED_API_KEY is not configured")
        async with build_http_client(self._settings.http_timeout_seconds) as client:
            try:
                payload = await self._get(client, release_id)
            except httpx.HTTPError as exc:
                raise FredCalendarError(f"FRED release/dates request failed: {exc}") from exc

        dates = []
        for entry in payload.get("release_dates", []):
            raw_date = entry.get("date")
            if not raw_date:
                continue
            try:
                dates.append(datetime.fromisoformat(raw_date).date())
            except ValueError:
                logger.warning("FRED release/dates: unparseable date %r", raw_date)
        return dates


def to_event_datetime(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=UTC)
