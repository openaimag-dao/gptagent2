from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api import history
from app.services.history.schemas import Timeframe


def _fake_config(**overrides):
    defaults = dict(
        symbol="BTC",
        model=SimpleNamespace(),
        provider=SimpleNamespace(),
        timeframes=(Timeframe.DAILY, Timeframe.FOUR_HOUR, Timeframe.ONE_HOUR),
        market="crypto",
        realtime_timeframes=(Timeframe.FIVE_MINUTE, Timeframe.FIFTEEN_MINUTE),
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_row(**overrides):
    defaults = dict(
        timestamp=datetime(2026, 8, 25, tzinfo=UTC),
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=1000.0,
        return_pct=None,
        volatility=None,
        atr=None,
        rsi=None,
        macd=None,
        macd_signal=None,
        macd_histogram=None,
        sma_20=None,
        sma_50=None,
        sma_200=None,
        volume_change_pct=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


async def test_get_history_404s_for_an_unknown_symbol():
    with patch("app.api.history.find_symbol_config", return_value=None):
        with pytest.raises(Exception) as exc_info:
            await history.get_history("NOPE")
    assert exc_info.value.status_code == 404


async def test_get_history_400s_for_an_invalid_timeframe_string():
    with patch("app.api.history.find_symbol_config", return_value=_fake_config()):
        with pytest.raises(Exception) as exc_info:
            await history.get_history("BTC", timeframe="3m")
    assert exc_info.value.status_code == 400


async def test_get_history_400s_when_the_symbol_has_neither_synced_nor_realtime_data_for_it():
    config = _fake_config(timeframes=(Timeframe.DAILY,), realtime_timeframes=())
    with patch("app.api.history.find_symbol_config", return_value=config):
        with pytest.raises(Exception) as exc_info:
            await history.get_history("BTC", timeframe="1h")
    assert exc_info.value.status_code == 400


async def test_get_history_serves_a_synced_timeframe():
    config = _fake_config()
    with (
        patch("app.api.history.find_symbol_config", return_value=config),
        patch("app.api.history.get_recent_series", AsyncMock(return_value=[_fake_row()])),
    ):
        payload = await history.get_history("BTC", timeframe="1d")
    assert payload["symbol"] == "BTC"
    assert payload["timeframe"] == "1d"
    assert payload["count"] == 1
    assert payload["candles"][0]["close"] == 100.5


async def test_get_history_serves_a_realtime_only_timeframe_not_in_the_sync_tuple():
    # 5m is only in config.realtime_timeframes, never config.timeframes --
    # the whole point of the two separate tuples (registry.py).
    config = _fake_config()
    with (
        patch("app.api.history.find_symbol_config", return_value=config),
        patch("app.api.history.get_recent_series", AsyncMock(return_value=[_fake_row()])),
    ):
        payload = await history.get_history("BTC", timeframe="5m")
    assert payload["timeframe"] == "5m"
    assert payload["count"] == 1


async def test_get_history_404s_when_nothing_has_been_synced_yet():
    config = _fake_config()
    with (
        patch("app.api.history.find_symbol_config", return_value=config),
        patch("app.api.history.get_recent_series", AsyncMock(return_value=[])),
    ):
        with pytest.raises(Exception) as exc_info:
            await history.get_history("BTC", timeframe="1d")
    assert exc_info.value.status_code == 404


async def test_get_history_passes_the_requested_limit_through_to_the_bounded_read():
    config = _fake_config()
    mock_get_recent = AsyncMock(return_value=[_fake_row()])
    with (
        patch("app.api.history.find_symbol_config", return_value=config),
        patch("app.api.history.get_recent_series", mock_get_recent),
    ):
        await history.get_history("BTC", timeframe="1d", limit=180)
    mock_get_recent.assert_awaited_once()
    assert mock_get_recent.call_args.args[-1] == 180
