"""Prediction Quality Lab Engine -- the I/O wrapper around
app.services.quality.metrics: reuses the exact same graded-prediction
join (app.services.learning.engine.evaluate_predictions()) LearningEngine
already uses for its plain accuracy_pct, and layers Brier score,
precision/recall, calibration, average error, and time-horizon accuracy
on top. No new persistence -- this reads the same ProbabilitySnapshot/
history rows LearningEngine already reads.
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.services.common.statistics import compute_wilson_interval
from app.services.history.schemas import Timeframe
from app.services.learning.engine import evaluate_predictions
from app.services.probability.engine import (
    compute_quantile_coverage,
    compute_quantile_coverage_by_group,
)
from app.services.quality.metrics import (
    compute_average_error,
    compute_brier_score,
    compute_calibration,
    compute_precision_recall,
    compute_time_horizon_accuracy,
)


class PredictionQualityEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def evaluate(
        self, symbol: str, model: type, timeframe: Timeframe = Timeframe.DAILY
    ) -> dict | None:
        evaluated = await evaluate_predictions(self._session_factory, symbol, model, timeframe)
        if not evaluated:
            return None

        accuracy_pct = round(100 * sum(1 for e in evaluated if e["correct"]) / len(evaluated), 2)
        settings = get_settings()
        calibration = compute_calibration(
            evaluated,
            bin_width=settings.calibration_bin_width_pct,
            min_sample_size=settings.calibration_min_sample_size,
            reliable_sample_size=settings.calibration_reliable_sample_size,
        )
        return {
            "symbol": symbol,
            "timeframe": timeframe.value,
            "evaluated_predictions": len(evaluated),
            "accuracy_pct": accuracy_pct,
            # POST-V9 Phase 15: accuracy_pct alone can't be judged as an
            # improvement or a regression without knowing how much sample
            # noise it could plausibly be explained by -- a Wilson interval
            # around the same correct/total count accuracy_pct is built from.
            "accuracy_ci": compute_wilson_interval(
                sum(1 for e in evaluated if e["correct"]), len(evaluated)
            ),
            "brier_score": compute_brier_score(evaluated),
            "precision_recall": compute_precision_recall(evaluated),
            "average_error_pct": compute_average_error(evaluated),
            "calibration": calibration,
            "time_horizon_accuracy": compute_time_horizon_accuracy(evaluated),
            # POST-V9 Phase 4: does the forecast engine's own p10-p90/p25-p75
            # quantile bands actually contain the realized outcome as often
            # as their definition claims (80%/50%)? Broken down by regime
            # and horizon so a healthy aggregate can't hide a regime/horizon
            # where coverage is badly off.
            "quantile_coverage": compute_quantile_coverage(
                evaluated,
                min_sample_size=settings.calibration_min_sample_size,
                reliable_sample_size=settings.calibration_reliable_sample_size,
            ),
            "quantile_coverage_by_regime": compute_quantile_coverage_by_group(
                evaluated,
                "reference_regime",
                min_sample_size=settings.calibration_min_sample_size,
                reliable_sample_size=settings.calibration_reliable_sample_size,
            ),
            "quantile_coverage_by_horizon": compute_quantile_coverage_by_group(
                evaluated,
                "horizon_periods",
                min_sample_size=settings.calibration_min_sample_size,
                reliable_sample_size=settings.calibration_reliable_sample_size,
            ),
            "computed_at": datetime.now(UTC).isoformat(),
        }
