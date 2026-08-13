from datetime import UTC, datetime
from unittest.mock import AsyncMock

from app.services.history.providers.fallback_provider import FallbackHistoricalProvider
from app.services.history.schemas import Candle, Timeframe


def _candle(source: str) -> Candle:
    return Candle(
        symbol="AAPL",
        timeframe=Timeframe.DAILY,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        open=1.0,
        high=1.0,
        low=1.0,
        close=1.0,
        source=source,
    )


def _mock_provider(name: str, candles: list[Candle] | None = None, raises: bool = False):
    provider = AsyncMock()
    provider.name = name
    if raises:
        provider.fetch_candles.side_effect = RuntimeError("boom")
    else:
        provider.fetch_candles.return_value = candles or []
    return provider


async def test_uses_primary_result_without_calling_fallback():
    primary = _mock_provider("primary", candles=[_candle("primary")])
    fallback = _mock_provider("fallback")
    provider = FallbackHistoricalProvider(primary, fallback)

    result = await provider.fetch_candles("AAPL", Timeframe.DAILY, None)

    assert result == [_candle("primary")]
    fallback.fetch_candles.assert_not_called()


async def test_falls_back_when_primary_returns_empty():
    primary = _mock_provider("primary", candles=[])
    fallback = _mock_provider("fallback", candles=[_candle("fallback")])
    provider = FallbackHistoricalProvider(primary, fallback)

    result = await provider.fetch_candles("AAPL", Timeframe.DAILY, None)

    assert result == [_candle("fallback")]
    fallback.fetch_candles.assert_awaited_once_with("AAPL", Timeframe.DAILY, None)


async def test_falls_back_when_primary_raises():
    primary = _mock_provider("primary", raises=True)
    fallback = _mock_provider("fallback", candles=[_candle("fallback")])
    provider = FallbackHistoricalProvider(primary, fallback)

    result = await provider.fetch_candles("AAPL", Timeframe.DAILY, None)

    assert result == [_candle("fallback")]


async def test_returns_empty_when_both_empty():
    primary = _mock_provider("primary", candles=[])
    fallback = _mock_provider("fallback", candles=[])
    provider = FallbackHistoricalProvider(primary, fallback)

    result = await provider.fetch_candles("AAPL", Timeframe.DAILY, None)

    assert result == []


def test_name_combines_both_provider_names():
    primary = _mock_provider("primary")
    fallback = _mock_provider("fallback")
    provider = FallbackHistoricalProvider(primary, fallback)

    assert provider.name == "primary+fallback_fallback"
