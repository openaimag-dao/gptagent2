from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.services.conviction.engine import (
    ConvictionEngine,
    _data_quality_multiplier,
    _quality_multiplier,
    classify_conviction,
)
from app.services.history.schemas import Timeframe


def test_low_confidence_is_weak():
    result = classify_conviction(10)
    assert result["tier"] == "Weak"
    assert result["alert_eligible"] is False


def test_medium_band():
    result = classify_conviction(45)
    assert result["tier"] == "Medium"


def test_strong_band_is_alert_eligible():
    result = classify_conviction(70)
    assert result["tier"] == "Strong"
    assert result["alert_eligible"] is True


def test_very_strong_without_sample_size():
    result = classify_conviction(90)
    assert result["tier"] == "Very Strong"


def test_high_confidence_without_sample_size_never_reaches_institutional():
    result = classify_conviction(99)
    assert result["tier"] == "Very Strong"


def test_high_confidence_with_large_sample_reaches_institutional():
    result = classify_conviction(99, sample_size=100)
    assert result["tier"] == "Institutional"


def test_high_confidence_with_small_sample_is_scaled_down():
    result = classify_conviction(99, sample_size=2, min_sample_size=30)
    assert result["tier"] in ("Weak", "Medium")
    assert result["effective_confidence_pct"] < 99


def test_quality_multiplier_is_none_without_enough_track_record():
    assert _quality_multiplier(None, None, 10) is None
    assert _quality_multiplier(0.1, None, 10) is None
    assert _quality_multiplier(0.1, 5, 10) is None


def test_quality_multiplier_is_one_for_perfect_calibration():
    assert _quality_multiplier(0.0, 20, 10) == 1.0


def test_quality_multiplier_is_zero_at_or_below_uninformative_baseline():
    assert _quality_multiplier(2 / 3, 20, 10) == 0.0
    assert _quality_multiplier(1.0, 20, 10) == 0.0


def test_quality_multiplier_scales_between_the_two_extremes():
    multiplier = _quality_multiplier(1 / 3, 20, 10)
    assert 0.0 < multiplier < 1.0


def test_classify_conviction_has_no_quality_multiplier_without_brier_score():
    result = classify_conviction(90, sample_size=50)
    assert result["quality_multiplier"] is None


def test_classify_conviction_ignores_a_too_small_quality_sample():
    with_small_quality_sample = classify_conviction(
        90, sample_size=50, brier_score=1.0, evaluated_predictions=3
    )
    without_quality_data = classify_conviction(90, sample_size=50)
    assert with_small_quality_sample["quality_multiplier"] is None
    assert (
        with_small_quality_sample["effective_confidence_pct"]
        == without_quality_data["effective_confidence_pct"]
    )


def test_classify_conviction_pulls_a_poorly_calibrated_symbol_down_to_weak():
    result = classify_conviction(99, sample_size=100, brier_score=2 / 3, evaluated_predictions=20)
    assert result["quality_multiplier"] == 0.0
    assert result["tier"] == "Weak"


def test_classify_conviction_leaves_well_calibrated_confidence_untouched():
    result = classify_conviction(90, sample_size=50, brier_score=0.0, evaluated_predictions=20)
    assert result["quality_multiplier"] == 1.0
    assert (
        result["effective_confidence_pct"]
        == classify_conviction(90, sample_size=50)["effective_confidence_pct"]
    )


# ---- POST-V9 Phase 12: data quality -> confidence link ----


def test_data_quality_multiplier_none_without_a_score():
    assert _data_quality_multiplier(None) is None


def test_data_quality_multiplier_full_strength_at_100():
    assert _data_quality_multiplier(100) == 1.0


def test_data_quality_multiplier_zero_at_0():
    assert _data_quality_multiplier(0) == 0.0


def test_data_quality_multiplier_scales_linearly():
    assert _data_quality_multiplier(80) == 0.8
    assert _data_quality_multiplier(60) == 0.6
    assert _data_quality_multiplier(40) == 0.4
    assert _data_quality_multiplier(20) == 0.2


def test_classify_conviction_data_quality_score_is_monotonic():
    # Same raw confidence, only data_quality_score varies -- effective
    # confidence must be non-increasing as data quality degrades, and the
    # multiplier itself must equal quality/100 at each step.
    scores_desc = (100, 80, 60, 40, 20)
    results = [classify_conviction(90, data_quality_score=score) for score in scores_desc]
    effective = [r["effective_confidence_pct"] for r in results]
    assert effective == sorted(effective, reverse=True)
    assert effective[0] > effective[-1]  # strictly worse, not just non-increasing
    for score, result in zip(scores_desc, results, strict=True):
        assert result["data_quality_multiplier"] == round(score / 100, 3)


def test_classify_conviction_no_data_quality_penalty_without_a_score():
    with_score = classify_conviction(90, data_quality_score=100)
    without_score = classify_conviction(90)
    assert with_score["effective_confidence_pct"] == without_score["effective_confidence_pct"]
    assert without_score["data_quality_multiplier"] is None


def test_classify_conviction_empty_data_pulls_confidence_to_zero():
    result = classify_conviction(90, data_quality_score=0)
    assert result["data_quality_multiplier"] == 0.0
    assert result["effective_confidence_pct"] == 0
    assert result["tier"] == "Weak"


def test_classify_conviction_composes_quality_and_data_quality_multipliers():
    result = classify_conviction(
        100,
        brier_score=0.0,
        evaluated_predictions=20,
        data_quality_score=50,
    )
    assert result["quality_multiplier"] == 1.0
    assert result["data_quality_multiplier"] == 0.5
    assert result["effective_confidence_pct"] == 50


async def test_evaluate_probability_folds_in_quality_engine_when_provided():
    probability_engine = AsyncMock()
    probability_engine.get_latest.return_value = SimpleNamespace(
        prob_up_pct=99, prob_down_pct=1, prob_flat_pct=0, sample_size=100
    )
    quality_engine = AsyncMock()
    quality_engine.evaluate.return_value = {
        "brier_score": 2 / 3,
        "evaluated_predictions": 20,
    }

    engine = ConvictionEngine(AsyncMock(), probability_engine, quality_engine)
    result = await engine.evaluate_probability("BTC", Timeframe.DAILY)

    quality_engine.evaluate.assert_awaited_once()
    assert result["quality_multiplier"] == 0.0
    assert result["tier"] == "Weak"


async def test_evaluate_probability_is_honest_without_a_quality_engine():
    probability_engine = AsyncMock()
    probability_engine.get_latest.return_value = SimpleNamespace(
        prob_up_pct=99, prob_down_pct=1, prob_flat_pct=0, sample_size=100
    )

    engine = ConvictionEngine(AsyncMock(), probability_engine)
    result = await engine.evaluate_probability("BTC", Timeframe.DAILY)

    assert result["quality_multiplier"] is None
    assert result["tier"] == "Institutional"


async def test_evaluate_probability_handles_no_graded_predictions_yet():
    probability_engine = AsyncMock()
    probability_engine.get_latest.return_value = SimpleNamespace(
        prob_up_pct=99, prob_down_pct=1, prob_flat_pct=0, sample_size=100
    )
    quality_engine = AsyncMock()
    quality_engine.evaluate.return_value = None

    engine = ConvictionEngine(AsyncMock(), probability_engine, quality_engine)
    result = await engine.evaluate_probability("BTC", Timeframe.DAILY)

    assert result["quality_multiplier"] is None
    assert result["tier"] == "Institutional"
