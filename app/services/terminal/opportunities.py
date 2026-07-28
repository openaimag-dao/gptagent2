"""Top Opportunities -- v4.0 Phase 7. No engine in this project ranks
tradeable symbols directly (RankingEngine ranks signal *factors*, not
symbols), so this composes a deterministic 0-100 opportunity score per
symbol from three already-computed, per-symbol signals: the empirical
probability edge (ProbabilityEngine), the latest breakout/breakdown
detection (BreakoutEngine), and the Portfolio Advisor's BUY/SELL/HOLD
call. Each component is honestly excluded (via
app.services.common.scoring.weighted_average) when that engine hasn't
produced a read for the symbol -- never defaulted to neutral.
"""

from app.services.common.scoring import center_scaled, weighted_average

_WEIGHTS: dict[str, float] = {"probability": 40.0, "breakout": 35.0, "advisor": 25.0}
_ADVISOR_SCORES: dict[str, float] = {"BUY": 80.0, "HOLD": 50.0, "SELL": 20.0}
_BULLISH_THRESHOLD = 60.0
_BEARISH_THRESHOLD = 40.0


def score_opportunity(
    probability_edge: float | None,
    breakout_probability_pct: float | None,
    breakout_direction: str | None,
    advisor_recommendation: str | None,
) -> float | None:
    """0-100, centered at 50 (neutral). None when none of the three
    signals have a read for this symbol -- never a guessed 50."""
    probability_component = (
        center_scaled(probability_edge, scale=0.5) if probability_edge is not None else None
    )

    breakout_component = None
    if breakout_probability_pct is not None and breakout_direction is not None:
        breakout_component = (
            breakout_probability_pct
            if breakout_direction == "bullish"
            else 100 - breakout_probability_pct
        )

    advisor_component = (
        _ADVISOR_SCORES.get(advisor_recommendation) if advisor_recommendation is not None else None
    )

    components = {
        "probability": probability_component,
        "breakout": breakout_component,
        "advisor": advisor_component,
    }
    return weighted_average(components, _WEIGHTS)


def classify_opportunity(score: float) -> str:
    if score >= _BULLISH_THRESHOLD:
        return "bullish"
    if score <= _BEARISH_THRESHOLD:
        return "bearish"
    return "neutral"
