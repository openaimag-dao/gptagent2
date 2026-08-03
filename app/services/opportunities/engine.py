"""Top Opportunities -- ranks the symbol universe BreakoutEngine already
scans (FEATURE_SYMBOLS) by the same probability_pct BreakoutEngine already
computes from its six confirmation checks. No new signal is invented here:
this module only reads BreakoutEngine's latest persisted detection per
symbol and adds a presentation-only rating label. A symbol with no recent
detection simply does not appear -- there is no "opportunity" to report on
a symbol nothing fired for.
"""

from app.database.models import BreakoutEvent

_STRONG_THRESHOLD = 75.0
_MODERATE_THRESHOLD = 60.0


def classify_opportunity_rating(direction: str, probability_pct: float | None) -> str:
    """Presentation-only mapping of a BreakoutEvent's direction and its own
    confirmation-weighted probability_pct onto a familiar rating scale.
    Never fabricates a rating when probability_pct is unavailable."""
    if probability_pct is None:
        return "Unrated"
    if direction == "bullish":
        if probability_pct >= _STRONG_THRESHOLD:
            return "Strong Buy"
        if probability_pct >= _MODERATE_THRESHOLD:
            return "Buy"
        return "Watch"
    if direction == "bearish":
        if probability_pct >= _STRONG_THRESHOLD:
            return "Strong Sell"
        if probability_pct >= _MODERATE_THRESHOLD:
            return "Sell"
        return "Watch"
    return "Watch"


def rank_opportunities(events: list[BreakoutEvent], limit: int = 10) -> list[dict]:
    """Sorts by probability_pct descending (events with no probability sort
    last) and serializes the fields Top Opportunities needs. Reuses every
    field straight off BreakoutEvent -- price, direction, risk_score,
    expected_continuation and reasoning are BreakoutEngine's own output,
    not recomputed here."""
    ranked = sorted(
        events,
        key=lambda e: e.probability_pct if e.probability_pct is not None else -1.0,
        reverse=True,
    )
    return [
        {
            "symbol": event.symbol,
            "price": float(event.price),
            "direction": event.direction,
            "probability_pct": (
                float(event.probability_pct) if event.probability_pct is not None else None
            ),
            "confidence_pct": event.confidence_pct,
            "risk_score": float(event.risk_score) if event.risk_score is not None else None,
            "rating": classify_opportunity_rating(event.direction, event.probability_pct),
            "expected_continuation": event.expected_continuation,
            "reasoning": event.reasoning,
            "computed_at": event.computed_at.isoformat(),
        }
        for event in ranked[:limit]
    ]
