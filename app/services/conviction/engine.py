"""Conviction Engine -- buckets an already-computed confidence percentage
into Weak / Medium / Strong / Very Strong / Institutional. Reuses
`compute_confidence_pct` (Sprint 9's Knowledge Rules sample-size discount)
rather than reimplementing "how much does a small sample shrink
confidence" a second time. "Institutional" additionally requires the
underlying sample to actually be large -- a single lucky high-confidence
read never qualifies just because the raw number is high.

`evaluate_probability` also folds in Prediction Quality Lab's own Brier
score for this exact symbol/timeframe when available -- a direct "has this
symbol's probability read actually been trustworthy historically" signal,
sitting right next to sample-size discounting but measuring something
sample size can't: a large sample of consistently miscalibrated
predictions still deserves low conviction.
"""

from app.services.history.registry import find_symbol_config
from app.services.history.schemas import Timeframe
from app.services.knowledge.rules import compute_confidence_pct
from app.services.probability.engine import ProbabilityEngine
from app.services.quality.engine import PredictionQualityEngine
from app.services.signals.engine import SignalEngine

_MIN_INSTITUTIONAL_SAMPLE_SIZE = 30

# Below this many graded predictions, Prediction Quality Lab's own Brier
# score is too noisy to act on -- treated the same as "no quality data",
# never as evidence of poor calibration.
_MIN_QUALITY_SAMPLE_SIZE = 10

# Brier score of a maximally uninformative 3-class forecast (33/33/33
# every time, regardless of outcome): 2 * (1/3)^2 + (2/3)^2 = 2/3. A real
# Brier score at or above this means the symbol's probability read has
# provided no more information than a coin flip -- the discount below
# scales from 1.0 (perfect calibration) to 0.0 (this baseline or worse).
_UNINFORMATIVE_BRIER_SCORE = 2 / 3

# (threshold, label) checked in descending order.
_TIERS: tuple[tuple[int, str], ...] = (
    (95, "Institutional"),
    (80, "Very Strong"),
    (60, "Strong"),
    (30, "Medium"),
    (0, "Weak"),
)


def _quality_multiplier(
    brier_score: float | None,
    evaluated_predictions: int | None,
    min_quality_sample_size: int,
) -> float | None:
    """Pure function: a Brier score + its graded-prediction count -> a
    0.0-1.0 discount, or None when there isn't enough of a track record to
    judge (no quality data, or too few graded predictions)."""
    if (
        brier_score is None
        or evaluated_predictions is None
        or evaluated_predictions < min_quality_sample_size
    ):
        return None
    return round(max(0.0, min(1.0, 1 - brier_score / _UNINFORMATIVE_BRIER_SCORE)), 3)


def classify_conviction(
    confidence_pct: int,
    sample_size: int | None = None,
    min_sample_size: int = _MIN_INSTITUTIONAL_SAMPLE_SIZE,
    brier_score: float | None = None,
    evaluated_predictions: int | None = None,
    min_quality_sample_size: int = _MIN_QUALITY_SAMPLE_SIZE,
) -> dict:
    """Pure function: raw confidence (+ optional sample size, + optional
    Prediction Quality Lab read) -> a conviction tier. When a sample size
    is given, the confidence used for tiering is first scaled down for
    small samples via the same formula Knowledge Rules already use; when a
    Brier score with enough graded predictions is given, it's then scaled
    again by how much better than an uninformative baseline that score is."""
    effective_confidence = confidence_pct
    if sample_size is not None:
        effective_confidence = compute_confidence_pct(confidence_pct, sample_size, min_sample_size)

    quality_multiplier = _quality_multiplier(
        brier_score, evaluated_predictions, min_quality_sample_size
    )
    if quality_multiplier is not None:
        effective_confidence *= quality_multiplier

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
                "quality_multiplier": quality_multiplier,
            }
    raise AssertionError("unreachable: _TIERS always matches at threshold 0")


class ConvictionEngine:
    """Evaluates conviction for the latest Signal and Probability reads --
    the two sources the Smart Alert Engine gates on."""

    def __init__(
        self,
        signal_engine: SignalEngine,
        probability_engine: ProbabilityEngine,
        quality_engine: PredictionQualityEngine | None = None,
    ) -> None:
        self._signal_engine = signal_engine
        self._probability_engine = probability_engine
        self._quality_engine = quality_engine

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

        brier_score: float | None = None
        evaluated_predictions: int | None = None
        if self._quality_engine is not None:
            config = find_symbol_config(symbol)
            if config is not None:
                quality = await self._quality_engine.evaluate(symbol, config.model, timeframe)
                if quality is not None:
                    brier_score = quality["brier_score"]
                    evaluated_predictions = quality["evaluated_predictions"]

        return classify_conviction(
            confidence_pct,
            sample_size=snapshot.sample_size,
            brier_score=brier_score,
            evaluated_predictions=evaluated_predictions,
        )
