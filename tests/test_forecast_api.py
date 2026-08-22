from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api import forecast


async def test_rejects_unknown_horizon():
    with pytest.raises(HTTPException) as exc_info:
        await forecast.get_forecast("BTC", horizon="99h")
    assert exc_info.value.status_code == 400


async def test_404_when_engine_returns_none():
    engine = AsyncMock()
    engine.compute.return_value = None
    with patch("app.api.forecast.build_forecast_engine", return_value=engine):
        with pytest.raises(HTTPException) as exc_info:
            await forecast.get_forecast("BTC", horizon="24h")
    assert exc_info.value.status_code == 404


def _explainability_engine(engine_breakdown=None, final_prediction=None):
    explainability_engine = AsyncMock()
    explainability_engine.build.return_value = {
        "engine_breakdown": engine_breakdown or [],
        "final_prediction": final_prediction or {},
    }
    return explainability_engine


@pytest.mark.parametrize("horizon", ["24h", "3d", "7d", "30d"])
async def test_every_horizon_reaches_the_engine(horizon):
    engine = AsyncMock()
    engine.compute.return_value = {"symbol": "BTC", "horizon": horizon}
    with (
        patch("app.api.forecast.build_forecast_engine", return_value=engine),
        patch("app.api.forecast.get_job_next_run", return_value=None),
        patch(
            "app.api.forecast.build_explainability_engine",
            return_value=_explainability_engine(),
        ),
    ):
        payload = await forecast.get_forecast("BTC", horizon=horizon)
    engine.compute.assert_awaited_once_with("BTC", horizon)
    assert payload["symbol"] == "BTC"
    assert payload["next_refresh_at"] is None


async def test_next_refresh_at_is_isoformatted():
    engine = AsyncMock()
    engine.compute.return_value = {"symbol": "BTC"}
    next_run = datetime(2026, 8, 3, 10, 0, tzinfo=UTC)
    with (
        patch("app.api.forecast.build_forecast_engine", return_value=engine),
        patch("app.api.forecast.get_job_next_run", return_value=next_run),
        patch(
            "app.api.forecast.build_explainability_engine",
            return_value=_explainability_engine(),
        ),
    ):
        payload = await forecast.get_forecast("BTC", horizon="24h")
    assert payload["next_refresh_at"] == next_run.isoformat()


async def test_ai_explanation_merges_engine_breakdown_and_final_prediction():
    engine = AsyncMock()
    engine.compute.return_value = {"symbol": "BTC"}
    breakdown = [{"name": "Technical Analysis", "signal": "Bullish"}]
    final_prediction = {"bias": "Strong Bullish", "agreement_score": 80.0}
    with (
        patch("app.api.forecast.build_forecast_engine", return_value=engine),
        patch("app.api.forecast.get_job_next_run", return_value=None),
        patch(
            "app.api.forecast.build_explainability_engine",
            return_value=_explainability_engine(breakdown, final_prediction),
        ),
    ):
        payload = await forecast.get_forecast("BTC", horizon="24h")
    assert payload["ai_explanation"]["engine_breakdown"] == breakdown
    assert payload["ai_explanation"]["final_prediction"] == final_prediction


async def test_horizon_consistency_reaches_the_payload():
    engine = AsyncMock()
    engine.compute.return_value = {"symbol": "BTC"}
    engine.get_horizon_consistency.return_value = {"consistency_pct": 66.7}
    with (
        patch("app.api.forecast.build_forecast_engine", return_value=engine),
        patch("app.api.forecast.get_job_next_run", return_value=None),
        patch(
            "app.api.forecast.build_explainability_engine",
            return_value=_explainability_engine(),
        ),
    ):
        payload = await forecast.get_forecast("BTC", horizon="24h")
    engine.get_horizon_consistency.assert_awaited_once_with("BTC")
    assert payload["horizon_consistency"] == {"consistency_pct": 66.7}


async def test_history_endpoint_serializes_snapshots():
    snapshot = SimpleNamespace(
        horizon="24h",
        computed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        current_price=100.0,
        target_price=103.0,
        direction="Bullish",
        probability_pct=70,
        confidence_tier="Medium",
        realized_price=None,
        error_pct=None,
        evaluated_at=None,
        forecast_version=1,
        forecast_status="ACTIVE",
        invalidation_reason=None,
        invalidated_at=None,
    )
    engine = AsyncMock()
    engine.get_latest_history.return_value = [snapshot]
    engine.summarize_accuracy.return_value = None
    with patch("app.api.forecast.build_forecast_engine", return_value=engine):
        result = await forecast.get_forecast_history("BTC")

    assert result["symbol"] == "BTC"
    assert result["forecasts"][0]["target_price"] == 103.0
    assert result["forecasts"][0]["realized_price"] is None
    assert result["forecasts"][0]["confidence_tier"] == "Medium"
    assert result["forecasts"][0]["forecast_version"] == 1
    assert result["forecasts"][0]["forecast_status"] == "ACTIVE"
    assert result["forecasts"][0]["invalidation_reason"] is None
    assert result["accuracy_by_horizon"]["24h"] == {
        "evaluated_count": 0,
        "avg_abs_error_pct": None,
        "win_rate_pct": None,
        "win_rate_sample_size": 0,
    }


async def test_history_endpoint_reports_real_accuracy_when_graded():
    engine = AsyncMock()
    engine.get_latest_history.return_value = []
    engine.summarize_accuracy.return_value = {"evaluated_count": 12, "avg_abs_error_pct": 0.8}
    with patch("app.api.forecast.build_forecast_engine", return_value=engine):
        result = await forecast.get_forecast_history("BTC")

    assert result["accuracy_by_horizon"]["24h"] == {
        "evaluated_count": 12,
        "avg_abs_error_pct": 0.8,
    }


def _official_row(**overrides):
    fields = {
        "id": 1,
        "symbol": "BTC",
        "current_price": 100.0,
        "target_price": 103.0,
        "expected_change_pct": 3.0,
        "direction": "Bullish",
        "probability_pct": 70,
        "confidence_tier": "Medium",
        "regime_at_forecast": "neutral",
        "official_forecast_date": datetime.now(UTC).date(),
        "computed_at": datetime.now(UTC),
        "forecast_status": "ACTIVE",
        "realized_price": None,
        "error_pct": None,
        "direction_correct": None,
        "target_reached": None,
        "max_favorable_excursion_pct": None,
        "max_adverse_excursion_pct": None,
        "error_type": None,
        "evaluated_at": None,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


# Root-cause fix for the "24H Forecast looks stale" report: /official/daily
# previously returned computed_at/forecast_status with no age/freshness
# signal at all, so a correctly-working once-per-UTC-day forecast (frozen
# by design) looked indistinguishable from a genuinely broken one. These
# pin the fix -- see app.api.forecast._with_official_freshness and
# app.config.settings's official_forecast_freshness_* fields.
async def test_official_daily_attaches_freshness_for_a_just_computed_row():
    from datetime import timedelta

    row = _official_row(computed_at=datetime.now(UTC) - timedelta(minutes=5))
    engine = AsyncMock()
    engine.get_official_daily.return_value = {"BTC": row}
    with (
        patch("app.api.forecast.build_forecast_engine", return_value=engine),
        patch("app.api.forecast._official_forecast_symbols", return_value=("BTC",)),
        patch("app.api.forecast.get_job_next_run", return_value=None),
    ):
        payload = await forecast.get_official_daily_forecasts()

    btc = payload["forecasts"][0]
    assert btc["freshness"] == "live"
    assert btc["is_stale"] is False
    assert 250 <= btc["age_seconds"] <= 350


async def test_official_daily_marks_a_day_old_row_stale():
    from datetime import timedelta

    row = _official_row(computed_at=datetime.now(UTC) - timedelta(hours=30))
    engine = AsyncMock()
    engine.get_official_daily.return_value = {"BTC": row}
    with (
        patch("app.api.forecast.build_forecast_engine", return_value=engine),
        patch("app.api.forecast._official_forecast_symbols", return_value=("BTC",)),
        patch("app.api.forecast.get_job_next_run", return_value=None),
    ):
        payload = await forecast.get_official_daily_forecasts()

    btc = payload["forecasts"][0]
    assert btc["freshness"] == "offline"
    assert btc["is_stale"] is True


async def test_official_daily_missing_symbol_has_no_freshness_fields():
    engine = AsyncMock()
    engine.get_official_daily.return_value = {}
    with (
        patch("app.api.forecast.build_forecast_engine", return_value=engine),
        patch("app.api.forecast._official_forecast_symbols", return_value=("BTC",)),
        patch("app.api.forecast.get_job_next_run", return_value=None),
    ):
        payload = await forecast.get_official_daily_forecasts()

    assert payload["forecasts"][0] == {"symbol": "BTC", "available": False}


async def test_official_daily_next_refresh_uses_the_official_job_id():
    engine = AsyncMock()
    engine.get_official_daily.return_value = {}
    next_run = datetime(2026, 8, 23, 0, 0, tzinfo=UTC)
    with (
        patch("app.api.forecast.build_forecast_engine", return_value=engine),
        patch("app.api.forecast._official_forecast_symbols", return_value=("BTC",)),
        patch("app.api.forecast.get_job_next_run", return_value=next_run) as mock_next_run,
    ):
        payload = await forecast.get_official_daily_forecasts()

    mock_next_run.assert_called_once_with(forecast.OFFICIAL_DAILY_FORECAST_JOB_ID)
    assert payload["next_refresh_at"] == next_run.isoformat()
