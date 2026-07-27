from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.history.pipeline import run_sync, run_validation, sync_and_validate
from app.services.history.registry import HistorySymbolConfig
from app.services.history.schemas import Timeframe
from app.services.history.sync import SyncOutcome


def _config(symbol="BTC", market="crypto") -> HistorySymbolConfig:
    return HistorySymbolConfig(
        symbol=symbol,
        model=object,
        provider=AsyncMock(),
        timeframes=(Timeframe.DAILY,),
        market=market,
    )


async def test_run_sync_delegates_to_history_sync_engine():
    outcome = SyncOutcome(symbol="BTC", timeframe=Timeframe.DAILY, candles_fetched=5)
    with patch("app.services.history.pipeline.HistorySyncEngine") as engine_cls:
        engine_cls.return_value.sync_all = AsyncMock(return_value=[outcome])
        session_factory = AsyncMock()
        registry = [_config()]

        await run_sync(session_factory, registry, years=10)

        engine_cls.assert_called_once_with(session_factory, registry=registry)
        engine_cls.return_value.sync_all.assert_awaited_once_with(lookback_years=10)


async def test_run_sync_logs_errors_without_raising():
    outcome = SyncOutcome(symbol="BTC", timeframe=Timeframe.DAILY, error="rate limited")
    with patch("app.services.history.pipeline.HistorySyncEngine") as engine_cls:
        engine_cls.return_value.sync_all = AsyncMock(return_value=[outcome])
        await run_sync(AsyncMock(), [_config()], years=10)  # must not raise


async def test_run_validation_repairs_duplicates_and_gaps_when_found():
    config = _config()
    with (
        patch(
            "app.services.history.pipeline.get_series",
            new=AsyncMock(return_value=[SimpleNamespace(timestamp="2026-01-01")]),
        ),
        patch("app.services.history.pipeline.find_duplicate_timestamps", return_value=["dup"]),
        patch("app.services.history.pipeline.find_gaps", return_value=["gap"]),
        patch(
            "app.services.history.pipeline.repair_duplicates", new=AsyncMock(return_value=1)
        ) as repair_dup,
        patch(
            "app.services.history.pipeline.repair_gaps", new=AsyncMock(return_value=2)
        ) as repair_gap,
    ):
        await run_validation(AsyncMock(), [config], repair=True)

        repair_dup.assert_awaited_once()
        repair_gap.assert_awaited_once()


async def test_run_validation_skips_repair_when_repair_false():
    config = _config()
    with (
        patch(
            "app.services.history.pipeline.get_series",
            new=AsyncMock(return_value=[SimpleNamespace(timestamp="2026-01-01")]),
        ),
        patch("app.services.history.pipeline.find_duplicate_timestamps", return_value=["dup"]),
        patch("app.services.history.pipeline.find_gaps", return_value=["gap"]),
        patch("app.services.history.pipeline.repair_duplicates", new=AsyncMock()) as repair_dup,
        patch("app.services.history.pipeline.repair_gaps", new=AsyncMock()) as repair_gap,
    ):
        await run_validation(AsyncMock(), [config], repair=False)

        repair_dup.assert_not_awaited()
        repair_gap.assert_not_awaited()


async def test_run_validation_continues_past_a_gap_repair_failure():
    """A rate-limited/failing provider call while repairing one symbol's gaps
    must not abort validation for the rest of the registry -- same
    fault-tolerance contract as HistorySyncEngine.sync_all()."""
    configs = [_config("BTC"), _config("ETH")]
    with (
        patch(
            "app.services.history.pipeline.get_series",
            new=AsyncMock(return_value=[SimpleNamespace(timestamp="2026-01-01")]),
        ),
        patch("app.services.history.pipeline.find_duplicate_timestamps", return_value=[]),
        patch("app.services.history.pipeline.find_gaps", return_value=["gap"]),
        patch(
            "app.services.history.pipeline.repair_gaps",
            new=AsyncMock(side_effect=[RuntimeError("429 Too Many Requests"), 2]),
        ) as repair_gap,
    ):
        await run_validation(AsyncMock(), configs, repair=True)  # must not raise

        assert repair_gap.await_count == 2


async def test_run_validation_continues_past_a_duplicate_repair_failure():
    with (
        patch(
            "app.services.history.pipeline.get_series",
            new=AsyncMock(return_value=[SimpleNamespace(timestamp="2026-01-01")]),
        ),
        patch("app.services.history.pipeline.find_duplicate_timestamps", return_value=["dup"]),
        patch("app.services.history.pipeline.find_gaps", return_value=[]),
        patch(
            "app.services.history.pipeline.repair_duplicates",
            new=AsyncMock(side_effect=RuntimeError("db error")),
        ),
    ):
        await run_validation(AsyncMock(), [_config()], repair=True)  # must not raise


async def test_run_validation_skips_symbols_with_no_stored_rows():
    with (
        patch("app.services.history.pipeline.get_series", new=AsyncMock(return_value=[])),
        patch("app.services.history.pipeline.find_duplicate_timestamps") as find_dupes,
    ):
        await run_validation(AsyncMock(), [_config()], repair=True)

        find_dupes.assert_not_called()


async def test_sync_and_validate_runs_both_stages_in_order():
    with (
        patch("app.services.history.pipeline.run_sync", new=AsyncMock()) as sync_mock,
        patch("app.services.history.pipeline.run_validation", new=AsyncMock()) as validate_mock,
    ):
        session_factory = AsyncMock()
        registry = [_config()]

        await sync_and_validate(session_factory, registry, years=5, repair=False)

        sync_mock.assert_awaited_once_with(session_factory, registry, 5)
        validate_mock.assert_awaited_once_with(session_factory, registry, repair=False)
