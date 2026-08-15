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
from app.services.history.schemas import Timeframe
from app.services.learning.engine import evaluate_predictions
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
            "brier_score": compute_brier_score(evaluated),
            "precision_recall": compute_precision_recall(evaluated),
            "average_error_pct": compute_average_error(evaluated),
            "calibration": calibration,
            "time_horizon_accuracy": compute_time_horizon_accuracy(evaluated),
            "computed_at": datetime.now(UTC).isoformat(),
        }
