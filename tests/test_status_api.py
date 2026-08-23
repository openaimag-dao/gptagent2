from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from app.api import status


async def test_status_includes_forecast_operational_health_block():
    forecast_engine = AsyncMock()
    forecast_engine.get_operational_health.return_value = {
        "last_prediction_created_at": "2026-08-23T00:00:00+00:00",
        "grading_pending_count": 2,
        "today_forecast_count": 4,
        "stale_forecast_count": 0,
    }
    job_status = {
        "last_run_at": datetime(2026, 8, 23, 12, 0, tzinfo=UTC),
        "last_success_at": datetime(2026, 8, 23, 12, 0, tzinfo=UTC),
        "last_failure_at": None,
        "last_failure_error": None,
    }

    with (
        patch("app.api.status.MarketRepository"),
        patch("app.api.status.NewsRepository"),
        patch("app.api.status.RegimeDetector") as mock_regime_cls,
        patch("app.api.status.SignalEngine") as mock_signal_cls,
        patch("app.api.status.GlobalScoreEngine") as mock_score_cls,
        patch("app.api.status.build_forecast_engine", return_value=forecast_engine),
        patch(
            "app.api.status.official_forecast_symbols", return_value=("BTC", "SOL", "LINK", "UNI")
        ),
        patch("app.api.status.get_job_run_status", return_value=job_status),
    ):
        mock_regime_cls.return_value.get_latest = AsyncMock(return_value=None)
        mock_signal_cls.return_value.get_latest = AsyncMock(return_value=None)
        mock_score_cls.return_value.get_latest = AsyncMock(return_value=None)

        payload = await status.get_status()

    forecast_engine.get_operational_health.assert_awaited_once_with(("BTC", "SOL", "LINK", "UNI"))
    forecast_block = payload["forecast"]
    assert forecast_block["grading_pending_count"] == 2
    assert forecast_block["today_forecast_count"] == 4
    assert forecast_block["intraday_job"]["last_run_at"] == "2026-08-23T12:00:00+00:00"
    assert forecast_block["intraday_job"]["last_failure_at"] is None
    assert forecast_block["official_daily_job"]["last_success_at"] == "2026-08-23T12:00:00+00:00"
    assert forecast_block["grading_job"]["last_run_at"] == "2026-08-23T12:00:00+00:00"


async def test_status_job_block_is_none_safe_for_a_job_that_never_ran():
    with (
        patch("app.api.status.MarketRepository"),
        patch("app.api.status.NewsRepository"),
        patch("app.api.status.RegimeDetector") as mock_regime_cls,
        patch("app.api.status.SignalEngine") as mock_signal_cls,
        patch("app.api.status.GlobalScoreEngine") as mock_score_cls,
        patch("app.api.status.build_forecast_engine") as mock_build_engine,
        patch("app.api.status.official_forecast_symbols", return_value=("BTC",)),
        patch("app.api.status.get_job_run_status", return_value=None),
    ):
        mock_regime_cls.return_value.get_latest = AsyncMock(return_value=None)
        mock_signal_cls.return_value.get_latest = AsyncMock(return_value=None)
        mock_score_cls.return_value.get_latest = AsyncMock(return_value=None)
        mock_build_engine.return_value.get_operational_health = AsyncMock(
            return_value={
                "last_prediction_created_at": None,
                "grading_pending_count": 0,
                "today_forecast_count": 0,
                "stale_forecast_count": 0,
            }
        )

        payload = await status.get_status()

    assert payload["forecast"]["intraday_job"] == {
        "last_run_at": None,
        "last_success_at": None,
        "last_failure_at": None,
        "last_failure_error": None,
    }
