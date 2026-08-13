from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import respx

from app.services.history.providers.twelvedata_provider import (
    TIME_SERIES_URL,
    TwelveDataHistoricalProvider,
)
from app.services.history.schemas import Timeframe


def _provider(api_key: str | None = "fake-key") -> TwelveDataHistoricalProvider:
    provider = TwelveDataHistoricalProvider()
    provider._settings = SimpleNamespace(twelvedata_api_key=api_key, http_timeout_seconds=5.0)
    return provider


def _no_pace():
    """_pace_request would otherwise real-sleep up to 8s between calls
    (module-level state persisting across tests in the same process) --
    every fetch_candles test below wraps its body in this so data-parsing
    behavior is tested in isolation from rate-limit pacing."""
    return patch(
        "app.services.history.providers.twelvedata_provider._pace_request", new=AsyncMock()
    )


async def test_returns_empty_without_api_key():
    with _no_pace():
        provider = _provider(api_key=None)
        result = await provider.fetch_candles("AAPL", Timeframe.DAILY, None)
    assert result == []


async def test_returns_empty_for_non_daily_timeframe():
    with _no_pace():
        provider = _provider()
        result = await provider.fetch_candles("AAPL", Timeframe.FOUR_HOUR, None)
    assert result == []


async def test_returns_empty_for_unmapped_symbol():
    """DXY and the indices are deliberately unmapped -- no Twelve Data
    free-tier symbol was found for them."""
    with _no_pace():
        provider = _provider()
        assert await provider.fetch_candles("DXY", Timeframe.DAILY, None) == []
        assert await provider.fetch_candles("NASDAQ", Timeframe.DAILY, None) == []


@respx.mock
async def test_parses_daily_candles_for_a_mapped_stock():
    respx.get(TIME_SERIES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "values": [
                    {
                        "datetime": "2026-01-02",
                        "open": "101.0",
                        "high": "102.0",
                        "low": "99.0",
                        "close": "100.0",
                        "volume": "1000",
                    },
                    {
                        "datetime": "2026-01-01",
                        "open": "96.0",
                        "high": "99.0",
                        "low": "95.0",
                        "close": "98.0",
                        "volume": "900",
                    },
                ],
            },
        )
    )
    with _no_pace():
        provider = _provider()
        candles = await provider.fetch_candles("AAPL", Timeframe.DAILY, None)

    assert len(candles) == 2
    assert candles[0].timestamp == datetime(2026, 1, 1, tzinfo=UTC)
    assert candles[1].timestamp == datetime(2026, 1, 2, tzinfo=UTC)
    assert candles[1].close == 100.0
    assert candles[0].source == "twelvedata_historical"


@respx.mock
async def test_filters_by_since():
    respx.get(TIME_SERIES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "values": [
                    {
                        "datetime": "2026-01-05",
                        "open": "1",
                        "high": "1",
                        "low": "1",
                        "close": "1",
                        "volume": "1",
                    },
                    {
                        "datetime": "2026-01-01",
                        "open": "1",
                        "high": "1",
                        "low": "1",
                        "close": "1",
                        "volume": "1",
                    },
                ],
            },
        )
    )
    with _no_pace():
        provider = _provider()
        candles = await provider.fetch_candles(
            "AAPL", Timeframe.DAILY, datetime(2026, 1, 3, tzinfo=UTC)
        )

    assert len(candles) == 1
    assert candles[0].timestamp == datetime(2026, 1, 5, tzinfo=UTC)


@respx.mock
async def test_parses_forex_pair_without_volume():
    respx.get(TIME_SERIES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "values": [
                    {
                        "datetime": "2026-01-01",
                        "open": "1.1",
                        "high": "1.2",
                        "low": "1.0",
                        "close": "1.15",
                    }
                ],
            },
        )
    )
    with _no_pace():
        provider = _provider()
        candles = await provider.fetch_candles("EURUSD", Timeframe.DAILY, None)

    assert len(candles) == 1
    assert candles[0].volume is None


@respx.mock
async def test_returns_empty_on_error_status():
    respx.get(TIME_SERIES_URL).mock(
        return_value=httpx.Response(200, json={"status": "error", "message": "bad symbol"})
    )
    with _no_pace():
        provider = _provider()
        result = await provider.fetch_candles("AAPL", Timeframe.DAILY, None)
    assert result == []


@respx.mock
async def test_returns_empty_on_http_error():
    respx.get(TIME_SERIES_URL).mock(return_value=httpx.Response(429))
    with _no_pace():
        provider = _provider()
        result = await provider.fetch_candles("AAPL", Timeframe.DAILY, None)
    assert result == []


@respx.mock
async def test_skips_malformed_rows_and_keeps_the_rest():
    respx.get(TIME_SERIES_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "status": "ok",
                "values": [
                    {
                        "datetime": "2026-01-01",
                        "open": "not-a-number",
                        "high": "1",
                        "low": "1",
                        "close": "1",
                    },
                    {
                        "datetime": "2026-01-02",
                        "open": "1",
                        "high": "1",
                        "low": "1",
                        "close": "1",
                        "volume": "1",
                    },
                ],
            },
        )
    )
    with _no_pace():
        provider = _provider()
        candles = await provider.fetch_candles("AAPL", Timeframe.DAILY, None)

    assert len(candles) == 1
    assert candles[0].timestamp == datetime(2026, 1, 2, tzinfo=UTC)


async def test_pace_request_waits_out_the_remaining_window():
    """Isolated test of the module-level rate limiter, with asyncio.sleep
    itself mocked so this doesn't actually wait 8 seconds."""
    import app.services.history.providers.twelvedata_provider as mod

    with patch.object(mod, "_last_call_at", mod.asyncio.get_event_loop().time()):
        with patch("asyncio.sleep", new=AsyncMock()) as mock_sleep:
            await mod._pace_request()
    mock_sleep.assert_awaited_once()
    args, _ = mock_sleep.call_args
    assert 0 < args[0] <= mod._MIN_CALL_INTERVAL_SECONDS
