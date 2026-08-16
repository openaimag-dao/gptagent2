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
