from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.history.schemas import Timeframe
from app.services.history.sync import HistorySyncEngine


def _config(provider_candles):
    provider = SimpleNamespace(fetch_candles=AsyncMock(return_value=provider_candles))
    return SimpleNamespace(model=object(), symbol="BTC", provider=provider)


async def test_four_hour_sync_upserts_with_do_update_true():
    # FOUR_HOUR is always resampled fresh from ONE_HOUR on every sync (see
    # providers/coingecko.py and providers/yfinance_provider.py) -- a
    # resampled bucket can start out incomplete and needs to be able to
    # overwrite itself as later syncs see fuller source data, so this must
    # never regress back to the default do_update=False (which live-verified
    # against production froze incomplete/flat 4h candles forever).
    engine = HistorySyncEngine(session_factory=SimpleNamespace())
    config = _config([])
    with (
        patch("app.services.history.sync.get_latest_timestamp", new=AsyncMock(return_value=None)),
        patch(
            "app.services.history.sync.upsert_candles", new=AsyncMock(return_value=0)
        ) as mock_upsert,
        patch("app.services.history.sync.fill_missing_indicators", new=AsyncMock(return_value=0)),
    ):
        await engine.sync_symbol_timeframe(config, Timeframe.FOUR_HOUR, lookback_years=1)

    mock_upsert.assert_awaited_once()
    assert mock_upsert.call_args.kwargs["do_update"] is True


async def test_daily_sync_upserts_with_do_update_false():
    # DAILY is fetched directly from the provider, never resampled --
    # do_update must stay off so a fetched candle's stored value is never
    # silently overwritten.
    engine = HistorySyncEngine(session_factory=SimpleNamespace())
    config = _config([])
    with (
        patch("app.services.history.sync.get_latest_timestamp", new=AsyncMock(return_value=None)),
        patch(
            "app.services.history.sync.upsert_candles", new=AsyncMock(return_value=0)
        ) as mock_upsert,
        patch("app.services.history.sync.fill_missing_indicators", new=AsyncMock(return_value=0)),
    ):
        await engine.sync_symbol_timeframe(config, Timeframe.DAILY, lookback_years=1)

    mock_upsert.assert_awaited_once()
    assert mock_upsert.call_args.kwargs["do_update"] is False


async def test_one_hour_sync_upserts_with_do_update_false():
    engine = HistorySyncEngine(session_factory=SimpleNamespace())
    config = _config([])
    with (
        patch("app.services.history.sync.get_latest_timestamp", new=AsyncMock(return_value=None)),
        patch(
            "app.services.history.sync.upsert_candles", new=AsyncMock(return_value=0)
        ) as mock_upsert,
        patch("app.services.history.sync.fill_missing_indicators", new=AsyncMock(return_value=0)),
    ):
        await engine.sync_symbol_timeframe(config, Timeframe.ONE_HOUR, lookback_years=1)

    mock_upsert.assert_awaited_once()
    assert mock_upsert.call_args.kwargs["do_update"] is False
