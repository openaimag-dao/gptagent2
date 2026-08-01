from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.history.schemas import Timeframe
from app.services.technical.provider import TechnicalAnalysisProvider


def _daily_row(i, close):
    return SimpleNamespace(
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i),
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=10.0,
    )


def _provider(tradingview_configured=False, tradingview_raw=None):
    tradingview_client = AsyncMock()
    tradingview_client.configured = tradingview_configured
    tradingview_client.fetch_indicators.return_value = tradingview_raw
    return TechnicalAnalysisProvider(AsyncMock(), tradingview_client), tradingview_client


async def test_get_indicators_rejects_unknown_timeframe():
    provider, _ = _provider()
    try:
        await provider.get_indicators("BTC", "3m")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


async def test_intraday_timeframe_unavailable_without_tradingview():
    provider, _ = _provider(tradingview_configured=False)
    result = await provider.get_indicators("BTC", "5m")
    assert result is None


async def test_intraday_timeframe_uses_tradingview_when_configured():
    provider, client = _provider(
        tradingview_configured=True, tradingview_raw={"price": 65000.0, "rsi": 55.0}
    )
    result = await provider.get_indicators("BTC", "5m")
    assert result is not None
    assert result.source == "tradingview"
    client.fetch_indicators.assert_awaited_once_with("BTC", "5m")


async def test_native_timeframe_falls_back_to_local_when_tradingview_unconfigured():
    provider, _ = _provider(tradingview_configured=False)
    rows = [_daily_row(i, 100.0 + i) for i in range(30)]
    with patch(
        "app.services.technical.provider.find_symbol_config",
        return_value=SimpleNamespace(model=object, timeframes=(Timeframe.DAILY,)),
    ):
        with patch("app.services.technical.provider.get_series", AsyncMock(return_value=rows)):
            result = await provider.get_indicators("BTC", "1d")
    assert result is not None
    assert result.source == "local"


async def test_native_timeframe_unavailable_when_symbol_not_in_registry():
    provider, _ = _provider(tradingview_configured=False)
    with patch("app.services.technical.provider.find_symbol_config", return_value=None):
        result = await provider.get_indicators("DOGE", "1d")
    assert result is None


async def test_weekly_timeframe_resamples_daily_history():
    provider, _ = _provider(tradingview_configured=False)
    rows = [_daily_row(i, 100.0 + i) for i in range(30)]
    with patch(
        "app.services.technical.provider.find_symbol_config",
        return_value=SimpleNamespace(model=object, timeframes=(Timeframe.DAILY,)),
    ):
        with patch("app.services.technical.provider.get_series", AsyncMock(return_value=rows)):
            result = await provider.get_indicators("BTC", "1w")
    assert result is not None
    assert result.timeframe == "1w"


async def test_get_daily_pair_trims_last_row_for_previous():
    provider, _ = _provider(tradingview_configured=False)
    rows = [_daily_row(i, 100.0 + i) for i in range(30)]
    with patch(
        "app.services.technical.provider.find_symbol_config",
        return_value=SimpleNamespace(model=object, timeframes=(Timeframe.DAILY,)),
    ):
        with patch("app.services.technical.provider.get_series", AsyncMock(return_value=rows)):
            current, previous = await provider.get_daily_pair("BTC")
    assert current is not None
    assert previous is not None
    assert current.price == rows[-1].close
    assert previous.price == rows[-2].close


async def test_get_daily_pair_none_when_symbol_not_in_registry():
    provider, _ = _provider(tradingview_configured=False)
    with patch("app.services.technical.provider.find_symbol_config", return_value=None):
        current, previous = await provider.get_daily_pair("DOGE")
    assert current is None
    assert previous is None


async def test_get_multi_timeframe_returns_reading_per_label():
    provider, _ = _provider(tradingview_configured=False)
    with patch("app.services.technical.provider.find_symbol_config", return_value=None):
        result = await provider.get_multi_timeframe("BTC", ("1h", "4h"))
    assert set(result.keys()) == {"1h", "4h"}
    assert result["1h"] is None
    assert result["4h"] is None
