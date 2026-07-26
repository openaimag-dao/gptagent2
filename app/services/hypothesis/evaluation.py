"""Pure hypothesis-comparison logic -- no I/O, no LLM judgment. Compares
two Research Engine results (compute_backtest_metrics' shape) by the
magnitude of their average return reaction, gated on a minimum sample
size so a hypothesis is never "accepted" or "rejected" off a handful of
occurrences -- it's reported honestly as inconclusive instead.
"""

_DEFAULT_MIN_OCCURRENCES = 3
_DEFAULT_MARGIN_PCT = 20.0


def evaluate_comparison(
    result_a: dict | None,
    result_b: dict | None,
    min_occurrences: int = _DEFAULT_MIN_OCCURRENCES,
    margin_pct: float = _DEFAULT_MARGIN_PCT,
) -> tuple[str, str]:
    """Returns (verdict, reason). verdict is one of "accepted", "rejected",
    "inconclusive" -- accepted means event_a's reaction was at least
    `margin_pct`% larger in magnitude than event_b's, rejected means the
    reverse, inconclusive covers everything too close to call or backed by
    too little data."""
    if result_a is None or result_b is None:
        return "inconclusive", "Not enough historical data for one or both events."
    if result_a["occurrences"] < min_occurrences or result_b["occurrences"] < min_occurrences:
        return (
            "inconclusive",
            f"Fewer than {min_occurrences} historical occurrences for one or both events "
            f"({result_a['occurrences']} vs {result_b['occurrences']}).",
        )

    magnitude_a = abs(result_a["avg_return_pct"])
    magnitude_b = abs(result_b["avg_return_pct"])

    if magnitude_a == 0 and magnitude_b == 0:
        return "inconclusive", "Both events show a ~0% average reaction."
    if magnitude_b == 0:
        return "accepted", f"{magnitude_a:.2f}% avg reaction vs ~0% -- no comparable baseline."

    relative_diff_pct = (magnitude_a - magnitude_b) / magnitude_b * 100
    if relative_diff_pct >= margin_pct:
        return (
            "accepted",
            f"{magnitude_a:.2f}% avg reaction vs {magnitude_b:.2f}% "
            f"({relative_diff_pct:.0f}% larger).",
        )
    if relative_diff_pct <= -margin_pct:
        return (
            "rejected",
            f"{magnitude_a:.2f}% avg reaction vs {magnitude_b:.2f}% "
            f"({abs(relative_diff_pct):.0f}% smaller).",
        )
    return (
        "inconclusive",
        f"Reactions too similar to distinguish ({magnitude_a:.2f}% vs {magnitude_b:.2f}%).",
    )
