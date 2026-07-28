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
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AgentPredictionLog, CryptoHistory
from app.services.agents.base import AgentOutput
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.learning.engine import realized_direction

_REFERENCE_SYMBOL = "BTC"
_HORIZON_PERIODS = 1

_DIRECTION_TO_PREDICTED = {"bullish": "up", "bearish": "down", "neutral": "flat"}


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
        history. Agents with none yet are absent, not defaulted."""
        rows = await get_series(
            self._session_factory, CryptoHistory, _REFERENCE_SYMBOL, Timeframe.DAILY
        )
        if not rows:
            return {}
        index_by_timestamp = {row.timestamp: i for i, row in enumerate(rows)}

        async with self._session_factory() as session:
            logs = list(await session.scalars(select(AgentPredictionLog)))

        correct_by_agent: dict[str, list[bool]] = {}
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
            correct_by_agent.setdefault(log.agent, []).append(predicted == realized)

        return {
            agent: round(100 * sum(results) / len(results), 1)
            for agent, results in correct_by_agent.items()
            if results
        }
