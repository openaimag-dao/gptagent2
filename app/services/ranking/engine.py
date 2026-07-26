"""Ranking Engine (V3 Phase 9): ranks the Signal Engine's factors by real
predictive power. Reuses StrategyLabEngine.walk_forward (Phase 4) with
folds=2 rather than a new backtest loop -- fold 1 (older half of stored
history) doubles as "historical importance", fold 2 (recent half) as
"current importance", so the same walk-forward machinery that checks a
strategy's consistency over time also gives a genuine current-vs-historical
comparison here for free.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import RankingSnapshot
from app.services.backtest.strategy_engine import StrategyLabEngine
from app.services.ranking.factors import FACTOR_CONDITIONS, edge_pct

logger = logging.getLogger(__name__)

_RANKING_FOLDS = 2


class RankingEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._strategy_engine = StrategyLabEngine(session_factory)

    async def rank_factors(self, target_symbol: str = "BTC") -> list[dict]:
        rows = []
        for name, condition in FACTOR_CONDITIONS.items():
            folds = await self._strategy_engine.walk_forward(
                [condition], target_symbol, folds=_RANKING_FOLDS
            )
            historical_metrics = folds[0]["metrics"] if len(folds) > 0 else None
            current_metrics = folds[1]["metrics"] if len(folds) > 1 else None
            rows.append(
                {
                    "factor": name,
                    "historical_importance_pct": edge_pct(historical_metrics),
                    "current_importance_pct": edge_pct(current_metrics),
                    "historical_metrics": historical_metrics,
                    "current_metrics": current_metrics,
                    "confidence": (
                        (current_metrics or {}).get("occurrences", 0)
                        + (historical_metrics or {}).get("occurrences", 0)
                    ),
                }
            )

        rows.sort(
            key=lambda r: (
                r["current_importance_pct"] is None,
                -(r["current_importance_pct"] or 0),
            )
        )
        for i, row in enumerate(rows):
            row["rank"] = i + 1
        return rows

    async def compute_and_store(self, target_symbol: str = "BTC") -> RankingSnapshot:
        rankings = await self.rank_factors(target_symbol)
        row = RankingSnapshot(target_symbol=target_symbol.upper(), rankings=rankings)
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def get_latest(self, target_symbol: str = "BTC") -> RankingSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(RankingSnapshot)
                .where(RankingSnapshot.target_symbol == target_symbol.upper())
                .order_by(RankingSnapshot.computed_at.desc())
                .limit(1)
            )
