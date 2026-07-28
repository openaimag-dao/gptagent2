from app.services.quality.metrics import (
    compute_average_error,
    compute_brier_score,
    compute_calibration,
    compute_precision_recall,
    compute_time_horizon_accuracy,
)


def _entry(prob_up, prob_down, prob_flat, predicted, realized, horizon_periods=1) -> dict:
    return {
        "prob_up_pct": prob_up,
        "prob_down_pct": prob_down,
        "prob_flat_pct": prob_flat,
        "predicted": predicted,
        "realized": realized,
        "correct": predicted == realized,
        "horizon_periods": horizon_periods,
    }


_EVALUATED = [
    _entry(70, 20, 10, "up", "up"),
    _entry(30, 60, 10, "down", "down"),
    _entry(50, 30, 20, "up", "down"),
    _entry(20, 20, 60, "flat", "flat", horizon_periods=7),
]


def test_compute_brier_score_matches_hand_calculation():
    assert compute_brier_score(_EVALUATED) == 0.355


def test_compute_brier_score_none_when_empty():
    assert compute_brier_score([]) is None


def test_compute_precision_recall_matches_hand_calculation():
    result = compute_precision_recall(_EVALUATED)

    assert result["per_class"]["up"] == {"precision_pct": 50.0, "recall_pct": 100.0, "support": 1}
    assert result["per_class"]["down"] == {
        "precision_pct": 100.0,
        "recall_pct": 50.0,
        "support": 2,
    }
    assert result["per_class"]["flat"] == {
        "precision_pct": 100.0,
        "recall_pct": 100.0,
        "support": 1,
    }
    assert result["macro_precision_pct"] == 83.33
    assert result["macro_recall_pct"] == 83.33


def test_compute_precision_recall_none_when_class_never_predicted_or_realized():
    evaluated = [_entry(80, 10, 10, "up", "up")]

    result = compute_precision_recall(evaluated)

    assert result["per_class"]["down"] == {"precision_pct": None, "recall_pct": None, "support": 0}
    assert result["per_class"]["flat"] == {"precision_pct": None, "recall_pct": None, "support": 0}


def test_compute_average_error_matches_hand_calculation():
    assert compute_average_error(_EVALUATED) == 40.0


def test_compute_average_error_none_when_empty():
    assert compute_average_error([]) is None


def test_compute_calibration_buckets_by_predicted_confidence():
    buckets = {b["confidence_bucket"]: b for b in compute_calibration(_EVALUATED)}

    assert buckets["40-60%"]["count"] == 1
    assert buckets["40-60%"]["avg_predicted_confidence_pct"] == 50.0
    assert buckets["40-60%"]["observed_accuracy_pct"] == 0.0
    assert buckets["40-60%"]["calibration_gap_pct"] == 50.0

    assert buckets["60-80%"]["count"] == 3
    assert buckets["60-80%"]["observed_accuracy_pct"] == 100.0


def test_compute_calibration_empty_when_no_predictions():
    assert compute_calibration([]) == []


def test_compute_time_horizon_accuracy_segments_by_horizon():
    result = {r["horizon_periods"]: r for r in compute_time_horizon_accuracy(_EVALUATED)}

    assert result[1]["count"] == 3
    assert round(result[1]["accuracy_pct"], 2) == 66.67
    assert result[7]["count"] == 1
    assert result[7]["accuracy_pct"] == 100.0
