"""Conviction Engine -- buckets an already-computed confidence percentage
into Weak / Medium / Strong / Very Strong / Institutional. Reuses
`compute_confidence_pct` (Sprint 9's Knowledge Rules sample-size discount)
rather than reimplementing "how much does a small sample shrink
confidence" a second time. "Institutional" additionally requires the
underlying sample to actually be large -- a single lucky high-confidence
read never qualifies just because the raw number is high.
"""

from app.services.history.schemas import Timeframe
from app.services.knowledge.rules import compute_confidence_pct
from app.services.probability.engine import ProbabilityEngine
from app.services.signals.engine import SignalEngine

_MIN_INSTITUTIONAL_SAMPLE_SIZE = 30

# (threshold, label) checked in descending order.
_TIERS: tuple[tuple[int, str], ...] = (
    (95, "Institutional"),
    (80, "Very Strong"),
    (60, "Strong"),
    (30, "Medium"),
    (0, "Weak"),
)


def classify_conviction(
    confidence_pct: int,
    sample_size: int | None = None,
    min_sample_size: int = _MIN_INSTITUTIONAL_SAMPLE_SIZE,
) -> dict:
    """Pure function: raw confidence (+ optional sample size) -> a
    conviction tier. When a sample size is given, the confidence used for
    tiering is first scaled down for small samples via the same formula
    Knowledge Rules already use."""
    effective_confidence = confidence_pct
    if sample_size is not None:
        effective_confidence = compute_confidence_pct(confidence_pct, sample_size, min_sample_size)

    for threshold, label in _TIERS:
        if effective_confidence >= threshold:
            if label == "Institutional" and (sample_size is None or sample_size < min_sample_size):
                label = "Very Strong"
            return {
                "tier": label,
                "raw_confidence_pct": confidence_pct,
                "effective_confidence_pct": round(effective_confidence),
                "sample_size": sample_size,
                "alert_eligible": label in ("Strong", "Very Strong", "Institutional"),
            }
    raise AssertionError("unreachable: _TIERS always matches at threshold 0")


class ConvictionEngine:
    """Evaluates conviction for the latest Signal and Probability reads --
    the two sources the Smart Alert Engine gates on."""

    def __init__(self, signal_engine: SignalEngine, probability_engine: ProbabilityEngine) -> None:
        self._signal_engine = signal_engine
        self._probability_engine = probability_engine

    async def evaluate_signal(self) -> dict | None:
        snapshot = await self._signal_engine.get_latest()
        if snapshot is None:
            return None
        return classify_conviction(snapshot.confidence_pct)

    async def evaluate_probability(
        self, symbol: str, timeframe: Timeframe = Timeframe.DAILY
    ) -> dict | None:
        snapshot = await self._probability_engine.get_latest(symbol, timeframe)
        if snapshot is None:
            return None
        confidence_pct = max(snapshot.prob_up_pct, snapshot.prob_down_pct, snapshot.prob_flat_pct)
        return classify_conviction(confidence_pct, sample_size=snapshot.sample_size)
