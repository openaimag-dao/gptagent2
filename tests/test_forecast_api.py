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


@pytest.mark.parametrize("horizon", ["24h", "3d", "7d", "30d"])
async def test_every_horizon_reaches_the_engine(horizon):
    engine = AsyncMock()
    engine.compute.return_value = {"symbol": "BTC", "horizon": horizon}
    with (
        patch("app.api.forecast.build_forecast_engine", return_value=engine),
        patch("app.api.forecast.get_job_next_run", return_value=None),
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
    ):
        payload = await forecast.get_forecast("BTC", horizon="24h")
    assert payload["next_refresh_at"] == next_run.isoformat()


async def test_history_endpoint_serializes_snapshots():
    snapshot = SimpleNamespace(
        horizon="24h",
        computed_at=datetime(2026, 8, 2, 0, 0, tzinfo=UTC),
        current_price=100.0,
        target_price=103.0,
        direction="Bullish",
        realized_price=None,
        error_pct=None,
        evaluated_at=None,
    )
    engine = AsyncMock()
    engine.get_latest_history.return_value = [snapshot]
    with patch("app.api.forecast.build_forecast_engine", return_value=engine):
        result = await forecast.get_forecast_history("BTC")

    assert result["symbol"] == "BTC"
    assert result["forecasts"][0]["target_price"] == 103.0
    assert result["forecasts"][0]["realized_price"] is None
