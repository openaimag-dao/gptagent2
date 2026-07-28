"""Prediction Quality Lab -- pure statistics over graded predictions
(app.services.learning.engine.evaluate_predictions()'s output: real
ProbabilitySnapshot rows joined against what actually happened, never a
guessed or simulated outcome). Computes the measures LearningEngine's
plain accuracy_pct doesn't: Brier score, per-class precision/recall,
a calibration curve, average calibration error, and accuracy segmented
by prediction horizon.
"""

_DIRECTIONS: tuple[str, ...] = ("up", "down", "flat")
_CALIBRATION_BIN_WIDTH = 20


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


def compute_calibration(
    evaluated: list[dict], bin_width: int = _CALIBRATION_BIN_WIDTH
) -> list[dict]:
    """Buckets predictions by their own stated confidence and compares
    the bucket's average confidence to its observed accuracy -- only
    buckets that actually have a prediction in them are reported."""
    buckets: dict[int, list[dict]] = {}
    for entry in evaluated:
        confidence = _confidence(entry)
        bin_start = min(int(confidence // bin_width) * bin_width, 100 - bin_width)
        buckets.setdefault(bin_start, []).append(entry)

    result = []
    for bin_start in sorted(buckets):
        entries = buckets[bin_start]
        avg_confidence = round(sum(_confidence(e) for e in entries) / len(entries), 2)
        observed_accuracy = round(100 * sum(1 for e in entries if e["correct"]) / len(entries), 2)
        result.append(
            {
                "confidence_bucket": f"{bin_start}-{bin_start + bin_width}%",
                "count": len(entries),
                "avg_predicted_confidence_pct": avg_confidence,
                "observed_accuracy_pct": observed_accuracy,
                "calibration_gap_pct": round(avg_confidence - observed_accuracy, 2),
            }
        )
    return result


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
