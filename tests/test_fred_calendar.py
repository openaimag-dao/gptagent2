from datetime import date
from types import SimpleNamespace

import httpx
import pytest
import respx

from app.services.calendar.fred_releases import (
    FRED_RELEASE_DATES_URL,
    FredCalendarError,
    FredReleaseCalendarClient,
    to_event_datetime,
)


def _client(api_key: str | None = "fake-key") -> FredReleaseCalendarClient:
    client = FredReleaseCalendarClient()
    client._settings = SimpleNamespace(fred_api_key=api_key, http_timeout_seconds=5.0)
    return client


async def test_raises_when_not_configured():
    client = _client(api_key=None)
    with pytest.raises(FredCalendarError, match="not configured"):
        await client.fetch_release_dates(10)


@respx.mock
async def test_parses_release_dates():
    respx.get(FRED_RELEASE_DATES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "release_dates": [
                    {"release_id": 10, "date": "2024-01-11"},
                    {"release_id": 10, "date": "2024-02-13"},
                ]
            },
        )
    )
    client = _client()

    result = await client.fetch_release_dates(10)

    assert result == [date(2024, 1, 11), date(2024, 2, 13)]


@respx.mock
async def test_skips_unparseable_dates():
    respx.get(FRED_RELEASE_DATES_URL).mock(
        return_value=httpx.Response(
            200,
            json={"release_dates": [{"date": "not-a-date"}, {"date": "2024-03-12"}]},
        )
    )
    client = _client()

    result = await client.fetch_release_dates(10)

    assert result == [date(2024, 3, 12)]


@respx.mock
async def test_raises_on_http_error():
    respx.get(FRED_RELEASE_DATES_URL).mock(return_value=httpx.Response(429))
    client = _client()

    with pytest.raises(FredCalendarError):
        await client.fetch_release_dates(10)


def test_to_event_datetime_is_midnight_utc():
    result = to_event_datetime(date(2024, 1, 11))
    assert result.isoformat() == "2024-01-11T00:00:00+00:00"
