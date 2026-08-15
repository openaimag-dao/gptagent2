from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.quality.engine import PredictionQualityEngine


def _entry(
    prob_up, prob_down, prob_flat, predicted, realized, realized_return_pct=None, **quantiles
) -> dict:
    return {
        "prob_up_pct": prob_up,
        "prob_down_pct": prob_down,
        "prob_flat_pct": prob_flat,
        "predicted": predicted,
        "realized": realized,
        "correct": predicted == realized,
        "horizon_periods": 1,
        "realized_return_pct": realized_return_pct,
        "p10_pct": quantiles.get("p10_pct"),
        "p25_pct": quantiles.get("p25_pct"),
        "p50_pct": quantiles.get("p50_pct"),
        "p75_pct": quantiles.get("p75_pct"),
        "p90_pct": quantiles.get("p90_pct"),
        "reference_regime": quantiles.get("reference_regime"),
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
    assert result["accuracy_ci"]["point_estimate_pct"] == 100.0
    assert result["accuracy_ci"]["sample_count"] == 2
    assert result["brier_score"] is not None
    assert result["precision_recall"]["macro_precision_pct"] == 100.0
    assert result["average_error_pct"] is not None
    assert result["calibration"]
    assert result["time_horizon_accuracy"] == [
        {"horizon_periods": 1, "count": 2, "accuracy_pct": 100.0}
    ]
    assert "computed_at" in result


async def test_evaluate_includes_quantile_coverage():
    evaluated = [
        _entry(70, 20, 10, "up", "up", realized_return_pct=1.0, p10_pct=-5.0, p90_pct=5.0),
        _entry(
            30,
            60,
            10,
            "down",
            "down",
            realized_return_pct=20.0,  # outside [-5, 5]
            p10_pct=-5.0,
            p90_pct=5.0,
        ),
    ]
    with patch(
        "app.services.quality.engine.evaluate_predictions",
        new=AsyncMock(return_value=evaluated),
    ):
        result = await PredictionQualityEngine(AsyncMock()).evaluate("BTC", object())

    assert result["quantile_coverage"]["p10_p90"]["sample_count"] == 2
    assert result["quantile_coverage"]["p10_p90"]["realized_coverage_pct"] == 50.0
    assert "quantile_coverage_by_regime" in result
    assert "quantile_coverage_by_horizon" in result
    # both entries share horizon_periods=1 (see _entry's default)
    assert result["quantile_coverage_by_horizon"][1]["p10_p90"]["sample_count"] == 2


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
