"""Terminal Engine -- v4.0 Phase 7 "Professional Telegram Terminal".

Composes engines this platform already has into digest views rather than
duplicating them: the Daily Brief assembles the AI Investment Committee
verdict, the current risk/liquidity read, Top Opportunities, the "main"
portfolio's health, and the latest Market Replay snapshot into one
message; Historical Comparison and the Weekly/Monthly performance digests
reuse MarketReplayEngine's own diff_snapshots() and the shared graded-
prediction join (evaluate_predictions()) rather than re-deriving either.
Critical Alerts, Market Replay, Committee Opinion, Risk Dashboard and
Portfolio Summary already exist as their own commands/broadcasts (Smart
Alert Engine, /replay, /committee, /risk, /portfolio) -- this only adds
the genuinely new composite views: Top Opportunities, the Daily Brief,
and Weekly Review/Monthly Performance (no weekly/monthly schedule existed
anywhere in this project before this phase).
"""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import CryptoHistory
from app.services.breakout.engine import BreakoutEngine
from app.services.committee.engine import CommitteeEngine
from app.services.global_score.engine import GlobalScoreEngine
from app.services.history.schemas import Timeframe
from app.services.learning.engine import evaluate_predictions
from app.services.memory.engine import MemoryEngine
from app.services.portfolio.advisor import PortfolioAdvisorEngine
from app.services.portfolio.engine import PortfolioEngine
from app.services.probability.engine import ProbabilityEngine
from app.services.replay.engine import MarketReplayEngine, diff_snapshots
from app.services.terminal.opportunities import classify_opportunity, score_opportunity

_OPPORTUNITY_SYMBOLS: tuple[str, ...] = ("BTC", "ETH", "SOL")
_DEFAULT_HISTORY_DAYS = 7


class TerminalEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        probability_engine: ProbabilityEngine,
        breakout_engine: BreakoutEngine,
        portfolio_advisor: PortfolioAdvisorEngine,
        portfolio_engine: PortfolioEngine,
        committee_engine: CommitteeEngine,
        global_score_engine: GlobalScoreEngine,
        replay_engine: MarketReplayEngine,
    ) -> None:
        self._session_factory = session_factory
        self._probability_engine = probability_engine
        self._breakout_engine = breakout_engine
        self._portfolio_advisor = portfolio_advisor
        self._portfolio_engine = portfolio_engine
        self._committee_engine = committee_engine
        self._global_score_engine = global_score_engine
        self._replay_engine = replay_engine

    async def _symbol_opportunity(self, symbol: str) -> dict | None:
        # The three lookups below are independent reads (different engines,
        # different tables) -- run concurrently rather than sequentially so
        # one symbol's opportunity costs one round-trip's latency, not three.
        probability_snapshot, breakout_event, advice = await asyncio.gather(
            self._probability_engine.get_latest(symbol, Timeframe.DAILY),
            self._breakout_engine.get_latest(symbol, Timeframe.DAILY),
            self._portfolio_advisor.advise(symbol, Timeframe.DAILY),
        )

        probability_edge = (
            probability_snapshot.prob_up_pct - probability_snapshot.prob_down_pct
            if probability_snapshot is not None
            else None
        )
        breakout_probability_pct = (
            float(breakout_event.probability_pct)
            if breakout_event is not None and breakout_event.probability_pct is not None
            else None
        )
        breakout_direction = breakout_event.direction if breakout_event is not None else None
        advisor_recommendation = advice.recommendation if advice is not None else None

        score = score_opportunity(
            probability_edge, breakout_probability_pct, breakout_direction, advisor_recommendation
        )
        if score is None:
            return None

        return {
            "symbol": symbol,
            "opportunity_score": round(score, 1),
            "classification": classify_opportunity(score),
            "probability_edge_pct": probability_edge,
            "breakout": (
                {
                    "event_type": breakout_event.event_type,
                    "direction": breakout_direction,
                    "probability_pct": breakout_probability_pct,
                }
                if breakout_event is not None
                else None
            ),
            "advisor_recommendation": advisor_recommendation,
        }

    async def compute_top_opportunities(
        self, symbols: tuple[str, ...] = _OPPORTUNITY_SYMBOLS
    ) -> list[dict]:
        # Symbols are independent of each other too, so the whole batch runs
        # as one concurrent wave rather than one symbol after another.
        per_symbol = await asyncio.gather(*(self._symbol_opportunity(s) for s in symbols))
        results = [r for r in per_symbol if r is not None]
        results.sort(key=lambda r: abs(r["opportunity_score"] - 50), reverse=True)
        return results

    async def compute_brief(self) -> dict:
        committee_verdict = await self._committee_engine.convene()
        global_score = await self._global_score_engine.get_latest()
        opportunities = await self.compute_top_opportunities()
        portfolio = await self._portfolio_engine.get_or_create("main")
        portfolio_health = await self._portfolio_engine.compute_health(portfolio.id)
        replay = await self._replay_engine.get_latest()

        return {
            "committee": committee_verdict.to_dict() if committee_verdict is not None else None,
            "risk": (
                {
                    "risk_off_score": global_score.risk_off_score,
                    "liquidity_score": global_score.liquidity_score,
                }
                if global_score is not None
                else None
            ),
            "top_opportunities": opportunities,
            "portfolio": portfolio_health,
            "regime": replay.regime if replay is not None else None,
            "health_score": replay.health_score if replay is not None else None,
            "computed_at": datetime.now(UTC).isoformat(),
        }

    async def compute_historical_comparison(
        self, days_ago: int = _DEFAULT_HISTORY_DAYS
    ) -> dict | None:
        latest = await self._replay_engine.get_latest()
        if latest is None:
            return None
        target_time = latest.computed_at - timedelta(days=days_ago)
        earlier = await self._replay_engine.get_nearest(target_time)
        if earlier is None or earlier.id == latest.id:
            return None
        return {"days_ago": days_ago, "diff": diff_snapshots(earlier, latest)}

    async def compute_period_performance(self, days: int) -> dict:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        evaluated = await evaluate_predictions(
            self._session_factory, "BTC", CryptoHistory, Timeframe.DAILY
        )
        period_evaluated = [e for e in evaluated if e["reference_timestamp"] >= cutoff]
        accuracy_pct = (
            round(100 * sum(1 for e in period_evaluated if e["correct"]) / len(period_evaluated), 2)
            if period_evaluated
            else None
        )

        memory_engine = MemoryEngine(self._session_factory)
        alerts = await memory_engine.get_category("alerts", limit=500, since=cutoff)

        return {
            "period_days": days,
            "evaluated_predictions": len(period_evaluated),
            "accuracy_pct": accuracy_pct,
            "alerts_count": len(alerts),
            "historical_comparison": await self.compute_historical_comparison(days_ago=days),
            "computed_at": datetime.now(UTC).isoformat(),
        }
