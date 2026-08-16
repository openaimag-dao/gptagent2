from app.services.quality.metrics import (
    classify_calibration_reliability,
    compute_average_error,
    compute_brier_score,
    compute_calibration,
    compute_calibration_by_regime_horizon,
    compute_expected_calibration_error,
    compute_log_loss,
    compute_precision_recall,
    compute_time_horizon_accuracy,
)


def _entry(
    prob_up, prob_down, prob_flat, predicted, realized, horizon_periods=1, reference_regime=None
) -> dict:
    return {
        "prob_up_pct": prob_up,
        "prob_down_pct": prob_down,
        "prob_flat_pct": prob_flat,
        "predicted": predicted,
        "realized": realized,
        "correct": predicted == realized,
        "horizon_periods": horizon_periods,
        "reference_regime": reference_regime,
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


# ---- Forecast Intelligence Upgrade: Log Loss + ECE --------------------------


def test_compute_log_loss_matches_hand_calculation():
    assert compute_log_loss(_EVALUATED) == 0.6456


def test_compute_log_loss_none_when_empty():
    assert compute_log_loss([]) is None


def test_compute_log_loss_is_unbounded_unlike_brier_score():
    # As confidence on the WRONG outcome approaches 100%, Log Loss grows
    # without bound while Brier score stays capped near 2.0 -- genuinely
    # different information from the same wrong call, which is the whole
    # point of adding Log Loss alongside the existing Brier score.
    very_confident_wrong = [_entry(99.9, 0.1, 0, "up", "down")]
    log_loss = compute_log_loss(very_confident_wrong)
    brier = compute_brier_score(very_confident_wrong)
    assert log_loss > 6.0  # -ln(0.001) ~= 6.9
    assert brier < 2.0


def test_compute_expected_calibration_error_matches_weighted_hand_calculation():
    buckets = [
        {"count": 10, "calibration_gap_pct": 5.0},
        {"count": 90, "calibration_gap_pct": 1.0},
    ]
    # (10*5.0 + 90*1.0) / 100 = 1.4
    assert compute_expected_calibration_error(buckets) == 1.4


def test_compute_expected_calibration_error_none_without_buckets():
    assert compute_expected_calibration_error([]) is None


def test_compute_expected_calibration_error_uses_absolute_gap():
    # A negative calibration_gap_pct (underconfident) must count the same
    # as an equal-magnitude positive one (overconfident) -- ECE measures
    # miscalibration magnitude, not direction.
    buckets = [{"count": 10, "calibration_gap_pct": -5.0}]
    assert compute_expected_calibration_error(buckets) == 5.0


# ---- Forecast Intelligence Upgrade: 2D regime x horizon calibration --------


def test_compute_calibration_by_regime_horizon_groups_by_combined_key():
    evaluated = [
        _entry(70, 20, 10, "up", "up", horizon_periods=1, reference_regime="bull"),
        _entry(70, 20, 10, "up", "down", horizon_periods=1, reference_regime="bull"),
        _entry(70, 20, 10, "up", "up", horizon_periods=7, reference_regime="bull"),
        _entry(70, 20, 10, "up", "up", horizon_periods=1, reference_regime="bear"),
    ]
    result = compute_calibration_by_regime_horizon(evaluated)
    keys = [(row["regime"], row["horizon_periods"]) for row in result]
    assert keys == [("bear", 1), ("bull", 1), ("bull", 7)]
    bull_1h = next(r for r in result if r["regime"] == "bull" and r["horizon_periods"] == 1)
    assert bull_1h["count"] == 2
    assert bull_1h["expected_calibration_error"] is not None


def test_compute_calibration_by_regime_horizon_groups_missing_dimensions_under_none():
    evaluated = [_entry(70, 20, 10, "up", "up")]  # no reference_regime set
    result = compute_calibration_by_regime_horizon(evaluated)
    assert result[0]["regime"] is None
    assert result[0]["count"] == 1


def test_compute_calibration_by_regime_horizon_empty_without_data():
    assert compute_calibration_by_regime_horizon([]) == []


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


def test_classify_calibration_reliability_thresholds():
    assert classify_calibration_reliability(5, min_sample_size=30, reliable_sample_size=100) == (
        "insufficient"
    )
    assert classify_calibration_reliability(30, min_sample_size=30, reliable_sample_size=100) == (
        "usable"
    )
    assert classify_calibration_reliability(99, min_sample_size=30, reliable_sample_size=100) == (
        "usable"
    )
    assert classify_calibration_reliability(100, min_sample_size=30, reliable_sample_size=100) == (
        "reliable"
    )


def test_compute_calibration_flags_small_buckets_as_insufficient():
    # _EVALUATED's buckets have counts of 1 and 3 -- both well under the
    # default 30-sample minimum, so both must be flagged, never presented
    # as trustworthy statistical evidence.
    buckets = {b["confidence_bucket"]: b for b in compute_calibration(_EVALUATED)}

    assert buckets["40-60%"]["sample_sufficiency"] == "insufficient"
    assert buckets["40-60%"]["calibration_warning"] is not None
    assert "1 graded prediction" in buckets["40-60%"]["calibration_warning"]

    assert buckets["60-80%"]["sample_sufficiency"] == "insufficient"


def test_compute_calibration_marks_reliable_bucket_when_sample_is_large():
    large_bucket = [_entry(70, 20, 10, "up", "up") for _ in range(150)]
    buckets = {b["confidence_bucket"]: b for b in compute_calibration(large_bucket)}

    assert buckets["60-80%"]["count"] == 150
    assert buckets["60-80%"]["sample_sufficiency"] == "reliable"
    assert buckets["60-80%"]["calibration_warning"] is None


def test_compute_calibration_respects_custom_thresholds():
    buckets = {
        b["confidence_bucket"]: b
        for b in compute_calibration(_EVALUATED, min_sample_size=1, reliable_sample_size=3)
    }
    assert buckets["40-60%"]["sample_sufficiency"] == "usable"  # count=1, >=1 but <3
    assert buckets["60-80%"]["sample_sufficiency"] == "reliable"  # count=3, >=3


def test_compute_time_horizon_accuracy_segments_by_horizon():
    result = {r["horizon_periods"]: r for r in compute_time_horizon_accuracy(_EVALUATED)}

    assert result[1]["count"] == 3
    assert round(result[1]["accuracy_pct"], 2) == 66.67
    assert result[7]["count"] == 1
    assert result[7]["accuracy_pct"] == 100.0
