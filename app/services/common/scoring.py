"""Shared pure scoring helpers used by every deterministic 0-100 composite
score in the project (Global Market Score, Scenario Engine, Portfolio
Health Score, ...). Kept in one place so the "signed real-world change ->
0-100 score centered at 50" mapping is defined once, not reimplemented per
engine.
"""


def clamp(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def center_scaled(value: float | None, scale: float, center: float = 50.0) -> float:
    """Maps a signed real-world change (e.g. +2.3%) onto a 0-100 score
    centered at 50 -- None (no data) also returns the neutral center."""
    if value is None:
        return center
    return clamp(center + value * scale)


def direction_from_score(
    score: float | None, center: float = 50.0
) -> tuple[str | None, float | None]:
    """Maps a 0-100 composite score (already centered at `center`, e.g. any
    score built with center_scaled()) onto a (direction, confidence) pair:
    "bullish"/"bearish"/"neutral" and a 0-100 confidence proportional to how
    far the score sits from center. None in, None out -- an agent with no
    underlying data reports no direction rather than a guessed "neutral".
    """
    if score is None:
        return None, None
    delta = score - center
    if delta > 0:
        direction = "bullish"
    elif delta < 0:
        direction = "bearish"
    else:
        direction = "neutral"
    confidence = clamp(abs(delta) * (100.0 / max(center, 100.0 - center)))
    return direction, confidence


def weighted_average(
    components: dict[str, float | None], weights: dict[str, float]
) -> float | None:
    """Weighted average over only the components that are actually
    available, renormalized over their weights -- a missing component is
    excluded rather than silently dragging the result toward a guessed
    default. Returns None if nothing is available."""
    available = {name: value for name, value in components.items() if value is not None}
    if not available:
        return None
    total_weight = sum(weights[name] for name in available)
    weighted_sum = sum(weights[name] * value for name, value in available.items())
    return weighted_sum / total_weight
