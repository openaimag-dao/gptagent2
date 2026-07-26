"""AI Hypothesis Engine (V3 Phase 8): tests generated hypotheses using the
Research Engine's real statistics, not an LLM's judgment -- see
evaluation.py for why. Reuses ResearchEngine.test_hypothesis (Phase 3)
rather than a second implementation of the event-return statistics."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Hypothesis
from app.services.hypothesis.evaluation import evaluate_comparison
from app.services.hypothesis.templates import (
    DEFAULT_EVENT_PAIRS,
    DEFAULT_SYMBOLS,
    HypothesisTemplate,
    generate_hypotheses,
)
from app.services.research.engine import ResearchEngine

logger = logging.getLogger(__name__)


class HypothesisEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._research_engine = ResearchEngine(session_factory)

    async def test(self, hypothesis: HypothesisTemplate) -> Hypothesis:
        result_a = await self._research_engine.test_hypothesis(
            hypothesis.symbol, hypothesis.event_a
        )
        result_b = await self._research_engine.test_hypothesis(
            hypothesis.symbol, hypothesis.event_b
        )
        verdict, reason = evaluate_comparison(result_a, result_b)

        row = Hypothesis(
            statement=hypothesis.statement,
            symbol=hypothesis.symbol,
            event_a=hypothesis.event_a,
            event_b=hypothesis.event_b,
            verdict=verdict,
            reason=reason,
            result_a=result_a,
            result_b=result_b,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def test_all(
        self,
        symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
        event_pairs: tuple[tuple[str, str], ...] = DEFAULT_EVENT_PAIRS,
    ) -> list[Hypothesis]:
        """One hypothesis failing to test never blocks the rest --
        matches this project's fault-tolerant batch pattern."""
        results = []
        for hypothesis in generate_hypotheses(symbols, event_pairs):
            try:
                results.append(await self.test(hypothesis))
            except Exception:
                logger.exception("Hypothesis test failed for: %s", hypothesis.statement)
        return results

    async def get_latest(self, limit: int = 50) -> list[Hypothesis]:
        async with self._session_factory() as session:
            return list(
                await session.scalars(
                    select(Hypothesis).order_by(Hypothesis.tested_at.desc()).limit(limit)
                )
            )
