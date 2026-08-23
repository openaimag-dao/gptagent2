import logging
from unittest.mock import AsyncMock, patch

import pytest

from app.scheduler.jobs import (
    _job_run_status,
    _timed,
    get_job_run_status,
    sync_crypto_daily_history_job,
)
from app.services.history.schemas import Timeframe


async def test_timed_calls_the_wrapped_job_and_forwards_args():
    calls = []

    async def sample_job(report_type: str) -> None:
        calls.append(report_type)

    await _timed(sample_job)("scheduled")

    assert calls == ["scheduled"]


async def test_timed_logs_a_duration_line_with_the_original_job_name(caplog):
    async def compute_forecast_job() -> None:
        return None

    with caplog.at_level(logging.INFO, logger="app.scheduler.jobs"):
        await _timed(compute_forecast_job)()

    assert any(
        "compute_forecast_job" in r.getMessage() and "ms" in r.getMessage() for r in caplog.records
    )


async def test_timed_preserves_the_wrapped_function_name():
    async def compute_forecast_job() -> None:
        return None

    wrapped = _timed(compute_forecast_job)
    assert wrapped.__name__ == "compute_forecast_job"


async def test_sync_crypto_daily_history_job_scopes_registry_to_crypto_daily_only():
    # Root-cause fix for the stale AI Forecast Center bug: this job must
    # only ever touch the crypto symbols/DAILY timeframe ForecastEngine
    # actually reads -- never the full ~25-symbol/4-provider registry
    # (stocks/macro/forex/FRED), which would add load to already-fragile
    # providers this job has no reason to touch.
    with patch("app.scheduler.jobs.run_sync", new=AsyncMock()) as mock_run_sync:
        await sync_crypto_daily_history_job()

    mock_run_sync.assert_awaited_once()
    _, registry_arg = mock_run_sync.call_args.args
    assert registry_arg  # non-empty
    assert all(config.market == "crypto" for config in registry_arg)
    assert all(config.timeframes == (Timeframe.DAILY,) for config in registry_arg)
    assert mock_run_sync.call_args.kwargs["years"] == 1


async def test_sync_crypto_daily_history_job_logs_and_swallows_a_run_sync_failure(caplog):
    with (
        patch("app.scheduler.jobs.run_sync", new=AsyncMock(side_effect=RuntimeError("boom"))),
        caplog.at_level(logging.ERROR, logger="app.scheduler.jobs"),
    ):
        await sync_crypto_daily_history_job()  # must not raise

    assert any("Crypto daily history sync job failed" in r.getMessage() for r in caplog.records)


def test_get_job_run_status_returns_none_for_a_job_that_has_never_run():
    assert get_job_run_status("a_job_name_nothing_ever_registers") is None


async def test_timed_records_last_run_and_last_success_on_success():
    async def _sample_job_success_case() -> None:
        return None

    with patch.dict(_job_run_status, {}, clear=True):
        await _timed(_sample_job_success_case)()
        status = get_job_run_status("_sample_job_success_case")

    assert status["last_run_at"] is not None
    assert status["last_success_at"] is not None
    assert status["last_failure_at"] is None
    assert status["last_failure_error"] is None


async def test_timed_records_last_failure_and_reraises_on_exception():
    async def _sample_job_failure_case() -> None:
        raise RuntimeError("boom")

    with patch.dict(_job_run_status, {}, clear=True):
        with pytest.raises(RuntimeError, match="boom"):
            await _timed(_sample_job_failure_case)()
        status = get_job_run_status("_sample_job_failure_case")

    assert status["last_run_at"] is not None
    assert status["last_success_at"] is None
    assert status["last_failure_at"] is not None
    assert status["last_failure_error"] == "boom"
