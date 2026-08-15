"""Agent Reliability Engine -- tracks each specialist agent's direction call
against what BTC's price actually did next, the same macro/market-wide proxy
every agent's direction already speaks to (see the Consensus Engine's own
documented limitation: these are macro-wide reads, not per-symbol calls).
Reuses LearningEngine's `realized_direction()` rather than reimplementing
"what actually happened" a second time -- this module only adds "who called
it correctly", the same append-only, evaluate-once-the-horizon-elapses
pattern LearningEngine already uses for ProbabilitySnapshot, applied to
agents instead of probability predictions.

Never fabricates a reliability score: an agent with zero evaluable
predictions yet is simply absent from the returned dict, not defaulted to
some baseline accuracy.

V9 Increment 8 hardens the accuracy estimate itself (still returned as the
exact same {agent_name: accuracy_pct} shape ConsensusEngine already
consumes) with two real-but-honest adjustments:
  - Bayesian shrinkage toward an uninformative 50% prior, so an agent with
    only 1-2 evaluated calls isn't treated as confidently 0% or 100%
    accurate off a tiny sample.
  - Recency (half-life) decay, so a stale track record from months ago
    counts for less than this week's calls -- an agent's reliability score
    tracks its CURRENT edge, not a diluted all-time average.
Explicitly NOT implemented here (see this module's own docstring for why
this is the honest boundary, not a gap): per-symbol/per-horizon reliability
(agents are BTC/basket-pinned by design -- see Portfolio Advisor's own
documented limitation) and inter-agent correlation/redundancy discounting
(no existing infrastructure measures agent-vs-agent vote correlation; would
need a new historical vote-correlation matrix, a materially larger
subsystem than this module's scope).
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import AgentPredictionLog, CryptoHistory
from app.services.agents.base import AgentOutput
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.learning.engine import realized_direction

_REFERENCE_SYMBOL = "BTC"
_HORIZON_PERIODS = 1
_PRIOR_ACCURACY_PCT = 50.0

_DIRECTION_TO_PREDICTED = {"bullish": "up", "bearish": "down", "neutral": "flat"}


def compute_shrunk_reliability_pct(
    results: list[tuple[bool, datetime]],
    reference_time: datetime,
    half_life_days: float,
    pseudo_count: float,
    prior_pct: float = _PRIOR_ACCURACY_PCT,
) -> float | None:
    """Pure function: an agent's (correct, prediction_timestamp) history ->
    one recency-decayed, shrinkage-adjusted accuracy percentage. Each result
    is weighted by 0.5 ** (age_days / half_life_days) -- older calls count
    for exponentially less -- then the decayed correct-fraction is pulled
    toward `prior_pct` by `pseudo_count` pseudo-observations (standard
    Bayesian-Beta-style shrinkage: a small decayed sample stays close to the
    prior, a large one is barely moved off its own raw accuracy). None
    (never a guessed score) when `results` is empty."""
    if not results:
        return None

    weighted_correct = 0.0
    total_weight = 0.0
    for correct, timestamp in results:
        age_days = max((reference_time - timestamp).total_seconds() / 86400, 0.0)
        weight = 0.5 ** (age_days / half_life_days) if half_life_days > 0 else 1.0
        weighted_correct += weight * (1.0 if correct else 0.0)
        total_weight += weight

    if total_weight == 0:
        return prior_pct

    raw_fraction = weighted_correct / total_weight
    shrunk_fraction = (raw_fraction * total_weight + (prior_pct / 100.0) * pseudo_count) / (
        total_weight + pseudo_count
    )
    return round(100 * shrunk_fraction, 1)


class AgentReliabilityEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def log(self, agent_outputs: dict[str, AgentOutput]) -> None:
        """Appends one row per agent that reported a direction this cycle,
        referenced against BTC's latest synced daily close -- never logs an
        agent with no direction (nothing to evaluate later)."""
        rows = await get_series(
            self._session_factory, CryptoHistory, _REFERENCE_SYMBOL, Timeframe.DAILY
        )
        if not rows:
            return
        reference_timestamp = rows[-1].timestamp

        entries = [
            AgentPredictionLog(
                agent=name,
                direction=output.direction,
                confidence=output.confidence,
                reference_timestamp=reference_timestamp,
                horizon_periods=_HORIZON_PERIODS,
            )
            for name, output in agent_outputs.items()
            if output.direction is not None
        ]
        if not entries:
            return
        async with self._session_factory() as session:
            session.add_all(entries)
            await session.commit()

    async def evaluate_reliability(self) -> dict[str, float]:
        """Returns {agent_name: accuracy_pct} for every agent with at least
        one prediction whose horizon has actually elapsed in stored BTC
        history. Agents with none yet are absent, not defaulted. The
        percentage itself is recency-decayed and shrinkage-adjusted (see
        `compute_shrunk_reliability_pct`), not a flat lifetime average."""
        rows = await get_series(
            self._session_factory, CryptoHistory, _REFERENCE_SYMBOL, Timeframe.DAILY
        )
        if not rows:
            return {}
        index_by_timestamp = {row.timestamp: i for i, row in enumerate(rows)}
        reference_time = rows[-1].timestamp

        async with self._session_factory() as session:
            logs = list(await session.scalars(select(AgentPredictionLog)))

        results_by_agent: dict[str, list[tuple[bool, datetime]]] = {}
        for log in logs:
            idx = index_by_timestamp.get(log.reference_timestamp)
            if idx is None:
                continue
            target_idx = idx + log.horizon_periods
            if target_idx >= len(rows):
                continue  # horizon hasn't elapsed in stored history yet

            reference_close = float(rows[idx].close)
            target_close = float(rows[target_idx].close)
            if reference_close == 0:
                continue
            realized_return_pct = 100 * (target_close - reference_close) / reference_close
            realized = realized_direction(realized_return_pct)
            predicted = _DIRECTION_TO_PREDICTED.get(log.direction)
            if predicted is None:
                continue
            results_by_agent.setdefault(log.agent, []).append(
                (predicted == realized, log.reference_timestamp)
            )

        settings = get_settings()
        scores = {
            agent: compute_shrunk_reliability_pct(
                results,
                reference_time,
                settings.reliability_recency_half_life_days,
                settings.reliability_shrinkage_pseudo_count,
            )
            for agent, results in results_by_agent.items()
            if results
        }
        return {agent: pct for agent, pct in scores.items() if pct is not None}
