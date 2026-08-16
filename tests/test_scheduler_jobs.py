import logging

from app.scheduler.jobs import _timed


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
