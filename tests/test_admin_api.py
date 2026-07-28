import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api import admin


@pytest.fixture(autouse=True)
def _reset_status():
    admin._status.update(state="idle", started_at=None, finished_at=None, error=None)
    yield
    admin._status.update(state="idle", started_at=None, finished_at=None, error=None)


async def test_trigger_starts_background_task_and_reports_running():
    started = asyncio.Event()

    async def _fake_sync(years: int) -> None:
        started.set()
        await asyncio.sleep(0.05)

    with patch("app.api.admin._run_history_sync", new=_fake_sync):
        result = await admin.trigger_history_sync(years=10)

        assert result["state"] == "running"
        assert result["started_at"] is not None
        await asyncio.wait_for(started.wait(), timeout=1)
        await asyncio.sleep(0.1)  # let the background task finish before the test ends


async def test_trigger_returns_already_running_without_starting_a_second_task():
    admin._status.update(state="running", started_at="2026-01-01T00:00:00+00:00")

    with patch("app.api.admin._run_history_sync", new=AsyncMock()) as run_mock:
        result = await admin.trigger_history_sync(years=10)

        assert result["state"] == "running"
        run_mock.assert_not_called()


async def test_status_endpoint_reflects_current_state():
    assert (await admin.get_history_sync_status())["state"] == "idle"

    admin._status.update(state="done")
    assert (await admin.get_history_sync_status())["state"] == "done"


async def test_run_history_sync_marks_done_on_success():
    with (
        patch("app.api.admin.run_sync", new=AsyncMock()),
        patch("app.api.admin.run_validation", new=AsyncMock()),
        patch("app.api.admin.build_registry", return_value=[]),
        patch("app.api.admin.get_session_factory", return_value=object()),
        patch("app.api.admin.EconomicCalendarEngine") as calendar_cls,
        patch("app.api.admin.seed_events", new=AsyncMock()),
    ):
        calendar_cls.return_value.sync_fred_releases = AsyncMock()
        calendar_cls.return_value.seed_central_bank_meetings = AsyncMock()

        await admin._run_history_sync(years=10)

        assert admin._status["state"] == "done"
        assert admin._status["finished_at"] is not None


async def test_run_history_sync_survives_calendar_sync_failure():
    """The calendar sync hits the same external, rate-limited APIs as the
    OHLCV backfill -- a failure there must not erase a sync that otherwise
    completed successfully."""
    with (
        patch("app.api.admin.run_sync", new=AsyncMock()),
        patch("app.api.admin.run_validation", new=AsyncMock()),
        patch("app.api.admin.build_registry", return_value=[]),
        patch("app.api.admin.get_session_factory", return_value=object()),
        patch(
            "app.api.admin.EconomicCalendarEngine",
            side_effect=RuntimeError("429 Too Many Requests"),
        ),
        patch("app.api.admin.seed_events", new=AsyncMock()),
    ):
        await admin._run_history_sync(years=10)

        assert admin._status["state"] == "done"


async def test_run_history_sync_marks_failed_on_exception():
    with (
        patch("app.api.admin.run_sync", new=AsyncMock(side_effect=RuntimeError("boom"))),
        patch("app.api.admin.build_registry", return_value=[]),
        patch("app.api.admin.get_session_factory", return_value=object()),
    ):
        await admin._run_history_sync(years=10)  # must not raise

        assert admin._status["state"] == "failed"
        assert admin._status["error"] == "boom"


async def test_trigger_migration_returns_ok_on_success():
    proc = AsyncMock()
    proc.communicate.return_value = (b"Running upgrade 0016 -> 0017\n", None)
    proc.returncode = 0

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
        result = await admin.trigger_migration()

    assert result["status"] == "ok"
    assert "0017" in result["output"]


async def test_trigger_migration_raises_500_on_failure():
    proc = AsyncMock()
    proc.communicate.return_value = (b"FAILED: some migration error\n", None)
    proc.returncode = 1

    with patch("asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
        with pytest.raises(HTTPException) as exc_info:
            await admin.trigger_migration()

    assert exc_info.value.status_code == 500
    assert "FAILED" in exc_info.value.detail
