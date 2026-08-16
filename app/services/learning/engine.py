"""Self-Learning Engine: compares every stored probability prediction against
what actually happened once enough time has passed, and reports real,
measured accuracy -- never a simulated or assumed number. A prediction only
enters the accuracy calculation once its `horizon_periods` have actually
elapsed in the stored history.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import ProbabilitySnapshot
from app.services.common.statistics import compute_wilson_interval
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe

logger = logging.getLogger(__name__)


def predicted_direction(prob_up_pct: int, prob_down_pct: int, prob_flat_pct: int) -> str:
    probs = {"up": prob_up_pct, "down": prob_down_pct, "flat": prob_flat_pct}
    return max(probs, key=probs.get)


def realized_direction(realized_return_pct: float) -> str:
    if realized_return_pct > 0:
        return "up"
    if realized_return_pct < 0:
        return "down"
    return "flat"


async def evaluate_predictions(
    session_factory: async_sessionmaker[AsyncSession],
    symbol: str,
    model: type,
    timeframe: Timeframe = Timeframe.DAILY,
) -> list[dict]:
    """Every graded prediction for symbol/timeframe: each stored
    ProbabilitySnapshot whose horizon has actually elapsed in stored
    history, joined against what really happened. A prediction only
    appears here once it's actually gradable -- never guessed. Shared by
    LearningEngine (aggregate accuracy) and PredictionQualityEngine
    (Brier score/precision/recall/calibration) so this join logic lives
    in exactly one place."""
    async with session_factory() as session:
        snapshots = list(
            await session.scalars(
                select(ProbabilitySnapshot)
                .where(
                    ProbabilitySnapshot.symbol == symbol,
                    ProbabilitySnapshot.timeframe == timeframe.value,
                    ProbabilitySnapshot.reference_timestamp.is_not(None),
                )
                .order_by(ProbabilitySnapshot.reference_timestamp)
            )
        )
    if not snapshots:
        return []

    rows = await get_series(session_factory, model, symbol, timeframe)
    index_by_timestamp = {r.timestamp: i for i, r in enumerate(rows)}

    evaluated = []
    for snapshot in snapshots:
        idx = index_by_timestamp.get(snapshot.reference_timestamp)
        if idx is None:
            continue
        target_idx = idx + snapshot.horizon_periods
        if target_idx >= len(rows):
            continue  # horizon hasn't elapsed in stored history yet

        reference_close = float(rows[idx].close)
        target_close = float(rows[target_idx].close)
        if reference_close == 0:
            continue
        realized_return_pct = 100 * (target_close - reference_close) / reference_close

        predicted = predicted_direction(
            snapshot.prob_up_pct, snapshot.prob_down_pct, snapshot.prob_flat_pct
        )
        realized = realized_direction(realized_return_pct)
        evaluated.append(
            {
                "reference_timestamp": snapshot.reference_timestamp,
                "horizon_periods": snapshot.horizon_periods,
                "prob_up_pct": snapshot.prob_up_pct,
                "prob_down_pct": snapshot.prob_down_pct,
                "prob_flat_pct": snapshot.prob_flat_pct,
                "predicted": predicted,
                "realized": realized,
                "correct": predicted == realized,
                "realized_return_pct": round(realized_return_pct, 2),
                # POST-V9 Phase 4: the same quantile band/regime already
                # stored on this snapshot at prediction time, carried
                # through so compute_quantile_coverage() can check it
                # against realized_return_pct above without a second join.
                "p10_pct": float(snapshot.p10_pct) if snapshot.p10_pct is not None else None,
                "p25_pct": float(snapshot.p25_pct) if snapshot.p25_pct is not None else None,
                "p50_pct": float(snapshot.p50_pct) if snapshot.p50_pct is not None else None,
                "p75_pct": float(snapshot.p75_pct) if snapshot.p75_pct is not None else None,
                "p90_pct": float(snapshot.p90_pct) if snapshot.p90_pct is not None else None,
                "reference_regime": snapshot.reference_regime,
            }
        )
    return evaluated


class LearningEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def evaluate_accuracy(
        self, symbol: str, model: type, timeframe: Timeframe = Timeframe.DAILY
    ) -> dict | None:
        evaluated = await evaluate_predictions(self._session_factory, symbol, model, timeframe)
        if not evaluated:
            return None

        correct = sum(1 for e in evaluated if e["correct"])
        accuracy_pct = round(100 * correct / len(evaluated), 2)
        return {
            "symbol": symbol,
            "timeframe": timeframe.value,
            "evaluated_predictions": len(evaluated),
            "accuracy_pct": accuracy_pct,
            # POST-V9 Phase 15: sample-size-aware uncertainty around
            # accuracy_pct, so it's never read as a settled number.
            "accuracy_ci": compute_wilson_interval(correct, len(evaluated)),
            "recent": evaluated[-10:],
        }
