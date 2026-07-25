"""User-submitted trading theories/rules, automatically backtested against
real stored history via the Backtest Engine. Distinct from
`knowledge.engine.KnowledgeEngine` (nearest-historical-analog search) --
this is the user-knowledge-base concept, kept in the same package since both
answer "what does history say," just from different starting points.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import KnowledgeRule, RuleCategory
from app.services.backtest.conditions import Condition
from app.services.backtest.engine import BacktestEngine

logger = logging.getLogger(__name__)

_MIN_OCCURRENCES_FOR_FULL_CONFIDENCE = 30


def compute_confidence_pct(
    win_rate_pct: float,
    occurrences: int,
    min_occurrences: int = _MIN_OCCURRENCES_FOR_FULL_CONFIDENCE,
) -> int:
    """Confidence scales the win rate down when there's little historical
    evidence -- a rule that fired twice and won both times is not as
    trustworthy as one that fired 50 times and won 70% of them."""
    sample_factor = min(1.0, occurrences / min_occurrences)
    return round(win_rate_pct * sample_factor)


def condition_to_dict(condition: Condition) -> dict:
    return {
        "symbol": condition.symbol,
        "field": condition.field,
        "operator": condition.operator,
        "value": condition.value,
    }


def condition_from_dict(data: dict) -> Condition:
    return Condition(
        symbol=data["symbol"], field=data["field"], operator=data["operator"], value=data["value"]
    )


class RuleEngine:
    """CRUD + automatic backtesting for user-submitted knowledge-base rules."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._backtest_engine = BacktestEngine(session_factory)

    async def create_rule(
        self,
        title: str,
        description: str,
        category: RuleCategory,
        author: str,
        target_symbol: str,
        conditions: list[Condition],
        horizon_periods: int = 1,
    ) -> KnowledgeRule:
        rule = KnowledgeRule(
            title=title,
            description=description,
            category=category,
            author=author,
            target_symbol=target_symbol.upper(),
            conditions=[condition_to_dict(c) for c in conditions],
            horizon_periods=horizon_periods,
        )
        async with self._session_factory() as session:
            session.add(rule)
            await session.commit()
            await session.refresh(rule)
            rule_id = rule.id

        return await self.backtest_rule(rule_id) or rule

    async def backtest_rule(self, rule_id: int) -> KnowledgeRule | None:
        async with self._session_factory() as session:
            rule = await session.get(KnowledgeRule, rule_id)
            if rule is None:
                return None
            conditions = [condition_from_dict(c) for c in rule.conditions]
            target_symbol = rule.target_symbol
            horizon_periods = rule.horizon_periods

        result = await self._backtest_engine.run(conditions, target_symbol, horizon=horizon_periods)

        async with self._session_factory() as session:
            rule = await session.get(KnowledgeRule, rule_id)
            if rule is None:
                return None
            if result is None:
                rule.occurrences = 0
                rule.win_rate_pct = None
                rule.avg_return_pct = None
                rule.max_drawdown_pct = None
                rule.profit_factor = None
                rule.sharpe_ratio = None
                rule.confidence_pct = None
            else:
                rule.occurrences = result["occurrences"]
                rule.win_rate_pct = result["win_rate_pct"]
                rule.avg_return_pct = result["avg_return_pct"]
                rule.max_drawdown_pct = result["max_drawdown_pct"]
                rule.profit_factor = result["profit_factor"]
                rule.sharpe_ratio = result["sharpe_ratio"]
                rule.confidence_pct = (
                    compute_confidence_pct(result["win_rate_pct"], result["occurrences"])
                    if result["win_rate_pct"] is not None
                    else None
                )
            rule.last_backtested_at = datetime.now(UTC)
            await session.commit()
            await session.refresh(rule)
            return rule

    async def list_rules(self) -> list[KnowledgeRule]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(KnowledgeRule).order_by(KnowledgeRule.created_at.desc())
            )
            return list(rows)

    async def get_rule(self, rule_id: int) -> KnowledgeRule | None:
        async with self._session_factory() as session:
            return await session.get(KnowledgeRule, rule_id)
