from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.learning.engine import (
    LearningEngine,
    evaluate_predictions,
    predicted_direction,
    realized_direction,
)


def test_predicted_direction_picks_the_max():
    assert predicted_direction(60, 30, 10) == "up"
    assert predicted_direction(10, 70, 20) == "down"
    assert predicted_direction(20, 20, 60) == "flat"


def test_realized_direction_positive_is_up():
    assert realized_direction(1.5) == "up"


def test_realized_direction_negative_is_down():
    assert realized_direction(-0.3) == "down"


def test_realized_direction_zero_is_flat():
    assert realized_direction(0.0) == "flat"


def _snapshot(reference_timestamp, horizon_periods=1, **quantiles):
    return SimpleNamespace(
        reference_timestamp=reference_timestamp,
        horizon_periods=horizon_periods,
        prob_up_pct=60,
        prob_down_pct=30,
        prob_flat_pct=10,
        p10_pct=quantiles.get("p10_pct"),
        p25_pct=quantiles.get("p25_pct"),
        p50_pct=quantiles.get("p50_pct"),
        p75_pct=quantiles.get("p75_pct"),
        p90_pct=quantiles.get("p90_pct"),
        reference_regime=quantiles.get("reference_regime"),
    )


def _row(timestamp, close):
    return SimpleNamespace(timestamp=timestamp, close=close)


async def test_evaluate_predictions_carries_quantile_bands_and_regime_through():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    rows = [_row(t0, 100.0), _row(t1, 110.0)]  # +10% realized
    snapshot = _snapshot(
        t0,
        p10_pct=-5.0,
        p25_pct=-2.0,
        p50_pct=1.0,
        p75_pct=4.0,
        p90_pct=9.0,
        reference_regime="bull",
    )

    session = AsyncMock()
    session.scalars.return_value = [snapshot]
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    with patch("app.services.learning.engine.get_series", AsyncMock(return_value=rows)):
        evaluated = await evaluate_predictions(session_factory, "BTC", object())

    assert len(evaluated) == 1
    entry = evaluated[0]
    assert entry["p10_pct"] == -5.0
    assert entry["p90_pct"] == 9.0
    assert entry["reference_regime"] == "bull"
    assert entry["realized_return_pct"] == 10.0


async def test_evaluate_predictions_quantile_fields_none_when_snapshot_has_none():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    rows = [_row(t0, 100.0), _row(t1, 105.0)]
    snapshot = _snapshot(t0)  # all quantile fields default to None

    session = AsyncMock()
    session.scalars.return_value = [snapshot]
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    with patch("app.services.learning.engine.get_series", AsyncMock(return_value=rows)):
        evaluated = await evaluate_predictions(session_factory, "BTC", object())

    entry = evaluated[0]
    assert entry["p10_pct"] is None
    assert entry["reference_regime"] is None


# ---- POST-V9 Phase 15: LearningEngine.evaluate_accuracy accuracy_ci ----


async def test_evaluate_accuracy_none_without_evaluated_predictions():
    with patch("app.services.learning.engine.evaluate_predictions", AsyncMock(return_value=[])):
        result = await LearningEngine(MagicMock()).evaluate_accuracy("BTC", object())
    assert result is None


async def test_evaluate_accuracy_includes_wilson_ci_around_accuracy_pct():
    evaluated = [
        {"correct": True, "reference_timestamp": None},
        {"correct": True, "reference_timestamp": None},
        {"correct": False, "reference_timestamp": None},
    ]
    with patch(
        "app.services.learning.engine.evaluate_predictions",
        AsyncMock(return_value=evaluated),
    ):
        result = await LearningEngine(MagicMock()).evaluate_accuracy("BTC", object())

    assert result["accuracy_pct"] == round(100 * 2 / 3, 2)
    assert result["accuracy_ci"]["point_estimate_pct"] == round(100 * 2 / 3, 2)
    assert result["accuracy_ci"]["sample_count"] == 3
    assert (
        result["accuracy_ci"]["lower_pct"]
        <= result["accuracy_pct"]
        <= result["accuracy_ci"]["upper_pct"]
    )
