"""Prediction Quality Lab -- pure statistics over graded predictions
(app.services.learning.engine.evaluate_predictions()'s output: real
ProbabilitySnapshot rows joined against what actually happened, never a
guessed or simulated outcome). Computes the measures LearningEngine's
plain accuracy_pct doesn't: Brier score, Log Loss, per-class precision/
recall, a calibration curve, a single Expected Calibration Error (ECE)
scalar over that curve, average calibration error, and accuracy
segmented by prediction horizon.
"""

import math

_DIRECTIONS: tuple[str, ...] = ("up", "down", "flat")
_CALIBRATION_BIN_WIDTH = 20
# Clamps a probability away from exactly 0/1 before taking its log, so one
# confidently-wrong call doesn't blow Log Loss up to +inf.
_LOG_LOSS_EPSILON = 1e-15

# Below this many graded predictions in a bucket, its own
# calibration_gap_pct is too noisy to trust -- POST-V9 Phase 3: a bucket
# with N=5 must not be presented as the same kind of statistical evidence
# as one with N=500. This is a *display/consumption* threshold (the bucket
# is still computed and returned, just flagged), not a hidden filter.
_MIN_CALIBRATION_BUCKET_SAMPLE_SIZE = 30
# A bucket at or above this size is treated as a fully reliable read; between
# the minimum and this size it's "usable but noisy" rather than either
# "trustworthy" or "insufficient".
_RELIABLE_CALIBRATION_BUCKET_SAMPLE_SIZE = 100


def _confidence(entry: dict) -> float:
    """The probability the model assigned to whatever direction it
    actually predicted (the argmax class) -- its own stated confidence."""
    return max(entry["prob_up_pct"], entry["prob_down_pct"], entry["prob_flat_pct"])


def compute_brier_score(evaluated: list[dict]) -> float | None:
    """Mean squared error between each class's predicted probability and
    the one-hot realized outcome, averaged across every graded
    prediction. 0 = perfect, higher = worse; None when there's nothing to
    grade rather than a fabricated 0."""
    if not evaluated:
        return None
    total = 0.0
    for entry in evaluated:
        for direction in _DIRECTIONS:
            prob = entry[f"prob_{direction}_pct"] / 100.0
            outcome = 1.0 if entry["realized"] == direction else 0.0
            total += (prob - outcome) ** 2
    return round(total / len(evaluated), 4)


def compute_log_loss(evaluated: list[dict]) -> float | None:
    """Forecast Intelligence Upgrade -- multiclass cross-entropy loss:
    -mean(log(probability the model assigned to the class that actually
    happened)), clipped away from exactly 0/1 (`_LOG_LOSS_EPSILON`) so a
    single confidently-wrong call doesn't blow the average up to +inf.
    Lower is better (0 = perfect). Unlike Brier score, this penalizes a
    confident WRONG call far more heavily than an uncertain one --
    genuinely different information from the squared-error measure
    Brier score already gives. None when there's nothing to grade rather
    than a fabricated 0."""
    if not evaluated:
        return None
    total = 0.0
    for entry in evaluated:
        prob = entry[f"prob_{entry['realized']}_pct"] / 100.0
        clipped = min(max(prob, _LOG_LOSS_EPSILON), 1 - _LOG_LOSS_EPSILON)
        total += -math.log(clipped)
    return round(total / len(evaluated), 4)


def compute_expected_calibration_error(calibration_buckets: list[dict]) -> float | None:
    """Forecast Intelligence Upgrade -- the standard Expected Calibration
    Error: the sample-weighted mean absolute gap between each bucket's
    average stated confidence and its observed accuracy, over the exact
    buckets `compute_calibration()` already computed (no re-bucketing) --
    the single-scalar summary of the whole calibration curve requested
    alongside the per-bucket detail, not a second measurement. None when
    there are no buckets to average (nothing graded yet)."""
    total_count = sum(bucket["count"] for bucket in calibration_buckets)
    if total_count == 0:
        return None
    weighted_gap = sum(
        abs(bucket["calibration_gap_pct"]) * bucket["count"] for bucket in calibration_buckets
    )
    return round(weighted_gap / total_count, 4)


def compute_precision_recall(evaluated: list[dict]) -> dict:
    """Per-class precision/recall from the predicted-vs-realized
    confusion matrix, plus macro averages over classes that actually had
    at least one qualifying prediction. A class never predicted or never
    realized reports None for that metric rather than a fabricated 0."""
    per_class: dict[str, dict] = {}
    for direction in _DIRECTIONS:
        true_positive = sum(
            1 for e in evaluated if e["predicted"] == direction and e["realized"] == direction
        )
        false_positive = sum(
            1 for e in evaluated if e["predicted"] == direction and e["realized"] != direction
        )
        false_negative = sum(
            1 for e in evaluated if e["predicted"] != direction and e["realized"] == direction
        )
        predicted_count = true_positive + false_positive
        actual_count = true_positive + false_negative
        per_class[direction] = {
            "precision_pct": (
                round(100 * true_positive / predicted_count, 2) if predicted_count > 0 else None
            ),
            "recall_pct": (
                round(100 * true_positive / actual_count, 2) if actual_count > 0 else None
            ),
            "support": actual_count,
        }

    precisions = [v["precision_pct"] for v in per_class.values() if v["precision_pct"] is not None]
    recalls = [v["recall_pct"] for v in per_class.values() if v["recall_pct"] is not None]
    return {
        "per_class": per_class,
        "macro_precision_pct": round(sum(precisions) / len(precisions), 2) if precisions else None,
        "macro_recall_pct": round(sum(recalls) / len(recalls), 2) if recalls else None,
    }


def compute_average_error(evaluated: list[dict]) -> float | None:
    """Mean absolute gap between each prediction's stated confidence and
    its actual correctness (100 if right, 0 if wrong) -- a well-calibrated
    model's confidence tracks how often it's actually right."""
    if not evaluated:
        return None
    errors = [abs(_confidence(entry) - (100.0 if entry["correct"] else 0.0)) for entry in evaluated]
    return round(sum(errors) / len(errors), 2)


def classify_calibration_reliability(
    count: int,
    min_sample_size: int = _MIN_CALIBRATION_BUCKET_SAMPLE_SIZE,
    reliable_sample_size: int = _RELIABLE_CALIBRATION_BUCKET_SAMPLE_SIZE,
) -> str:
    """Pure function: a bucket's own graded-prediction count -> one of
    "insufficient"/"usable"/"reliable". POST-V9 Phase 3: makes the
    statistical weight of a calibration bucket explicit instead of letting
    a bucket of N=5 read as equally meaningful as one of N=500."""
    if count < min_sample_size:
        return "insufficient"
    if count < reliable_sample_size:
        return "usable"
    return "reliable"


def compute_calibration(
    evaluated: list[dict],
    bin_width: int = _CALIBRATION_BIN_WIDTH,
    min_sample_size: int = _MIN_CALIBRATION_BUCKET_SAMPLE_SIZE,
    reliable_sample_size: int = _RELIABLE_CALIBRATION_BUCKET_SAMPLE_SIZE,
) -> list[dict]:
    """Buckets predictions by their own stated confidence and compares
    the bucket's average confidence to its observed accuracy -- only
    buckets that actually have a prediction in them are reported.

    POST-V9 Phase 3: every bucket also reports `sample_sufficiency`
    (`classify_calibration_reliability`'s own label) and a human-readable
    `calibration_warning` (None when the bucket is reliable) so a small
    sample is never presented as strong statistical evidence -- the bucket
    is still returned (never hidden), just honestly labeled."""
    buckets: dict[int, list[dict]] = {}
    for entry in evaluated:
        confidence = _confidence(entry)
        bin_start = min(int(confidence // bin_width) * bin_width, 100 - bin_width)
        buckets.setdefault(bin_start, []).append(entry)

    result = []
    for bin_start in sorted(buckets):
        entries = buckets[bin_start]
        count = len(entries)
        avg_confidence = round(sum(_confidence(e) for e in entries) / count, 2)
        observed_accuracy = round(100 * sum(1 for e in entries if e["correct"]) / count, 2)
        sufficiency = classify_calibration_reliability(count, min_sample_size, reliable_sample_size)
        warning = (
            None
            if sufficiency == "reliable"
            else (
                f"Only {count} graded prediction(s) in this bucket "
                f"(need {min_sample_size}+ to trust this calibration_gap_pct)"
                if sufficiency == "insufficient"
                else f"{count} graded predictions -- usable but not yet a reliable read "
                f"(need {reliable_sample_size}+ for high confidence)"
            )
        )
        result.append(
            {
                "confidence_bucket": f"{bin_start}-{bin_start + bin_width}%",
                "count": count,
                "avg_predicted_confidence_pct": avg_confidence,
                "observed_accuracy_pct": observed_accuracy,
                "calibration_gap_pct": round(avg_confidence - observed_accuracy, 2),
                "sample_sufficiency": sufficiency,
                "calibration_warning": warning,
            }
        )
    return result


def compute_calibration_by_regime_horizon(
    evaluated: list[dict],
    bin_width: int = _CALIBRATION_BIN_WIDTH,
    min_sample_size: int = _MIN_CALIBRATION_BUCKET_SAMPLE_SIZE,
    reliable_sample_size: int = _RELIABLE_CALIBRATION_BUCKET_SAMPLE_SIZE,
) -> list[dict]:
    """Forecast Intelligence Upgrade -- the 2D regime x horizon
    calibration matrix: calibration is only ever broken down one
    dimension at a time elsewhere (compute_calibration buckets by
    confidence; app.services.probability.engine.compute_quantile_coverage_by_group
    splits by regime OR horizon, never both together). A healthy
    aggregate ECE can hide one regime/horizon combination that's badly
    miscalibrated while others are fine.

    Groups `evaluated` by the (reference_regime, horizon_periods)
    combination, then runs the SAME `compute_calibration` bucketing and
    `compute_expected_calibration_error` scalar over just that slice --
    no new bucketing rule, just a finer partition of the existing one.
    Rows missing either dimension are grouped under a None key rather
    than silently dropped, so a caller can see how much data lacks it."""
    groups: dict[tuple, list[dict]] = {}
    for entry in evaluated:
        key = (entry.get("reference_regime"), entry.get("horizon_periods"))
        groups.setdefault(key, []).append(entry)

    result = []
    for (regime, horizon_periods), entries in groups.items():
        buckets = compute_calibration(entries, bin_width, min_sample_size, reliable_sample_size)
        result.append(
            {
                "regime": regime,
                "horizon_periods": horizon_periods,
                "count": len(entries),
                "expected_calibration_error": compute_expected_calibration_error(buckets),
            }
        )
    return sorted(result, key=lambda row: (row["regime"] or "", row["horizon_periods"] or 0))


def compute_time_horizon_accuracy(evaluated: list[dict]) -> list[dict]:
    """Accuracy segmented by each prediction's horizon_periods -- a
    single row when every prediction shares one horizon, more if horizons
    vary."""
    by_horizon: dict[int, list[dict]] = {}
    for entry in evaluated:
        by_horizon.setdefault(entry["horizon_periods"], []).append(entry)

    result = []
    for horizon in sorted(by_horizon):
        entries = by_horizon[horizon]
        accuracy = round(100 * sum(1 for e in entries if e["correct"]) / len(entries), 2)
        result.append({"horizon_periods": horizon, "count": len(entries), "accuracy_pct": accuracy})
    return result
