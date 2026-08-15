from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.quality.engine import PredictionQualityEngine


def _entry(prob_up, prob_down, prob_flat, predicted, realized) -> dict:
    return {
        "prob_up_pct": prob_up,
        "prob_down_pct": prob_down,
        "prob_flat_pct": prob_flat,
        "predicted": predicted,
        "realized": realized,
        "correct": predicted == realized,
        "horizon_periods": 1,
    }


async def test_evaluate_returns_none_when_nothing_graded():
    with patch("app.services.quality.engine.evaluate_predictions", new=AsyncMock(return_value=[])):
        result = await PredictionQualityEngine(AsyncMock()).evaluate("BTC", object())

    assert result is None


async def test_evaluate_assembles_all_quality_measures():
    evaluated = [
        _entry(70, 20, 10, "up", "up"),
        _entry(30, 60, 10, "down", "down"),
    ]
    with patch(
        "app.services.quality.engine.evaluate_predictions",
        new=AsyncMock(return_value=evaluated),
    ):
        result = await PredictionQualityEngine(AsyncMock()).evaluate("BTC", object())

    assert result["symbol"] == "BTC"
    assert result["evaluated_predictions"] == 2
    assert result["accuracy_pct"] == 100.0
    assert result["brier_score"] is not None
    assert result["precision_recall"]["macro_precision_pct"] == 100.0
    assert result["average_error_pct"] is not None
    assert result["calibration"]
    assert result["time_horizon_accuracy"] == [
        {"horizon_periods": 1, "count": 2, "accuracy_pct": 100.0}
    ]
    assert "computed_at" in result


async def test_evaluate_uses_configured_calibration_bin_width():
    evaluated = [_entry(72, 18, 10, "up", "up")]
    settings = SimpleNamespace(
        calibration_bin_width_pct=25,
        calibration_min_sample_size=30,
        calibration_reliable_sample_size=100,
    )
    with (
        patch(
            "app.services.quality.engine.evaluate_predictions",
            new=AsyncMock(return_value=evaluated),
        ),
        patch("app.services.quality.engine.get_settings", return_value=settings),
    ):
        result = await PredictionQualityEngine(AsyncMock()).evaluate("BTC", object())

    assert result["calibration"][0]["confidence_bucket"] == "50-75%"
