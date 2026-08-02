"""Market Replay Engine -- takes a single point-in-time snapshot consolidating
every other engine's already-computed latest read into one row: regime,
Global Score sub-scores, Consensus, per-agent outputs, Portfolio Advice,
macro/crypto prices, whale/ETF snapshots, news, the latest BTC probability
read, and every alert logged since the previous snapshot.

Consensus is the only thing actually computed here (it has no persistence
of its own elsewhere -- every other field is a direct read of a row another
engine already wrote via its own scheduled job). Every optional field is
honestly `None`/empty when the underlying engine hasn't produced a read
yet -- never a fabricated placeholder.
"""

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AssetPrice, MarketSnapshot, NewsItem
from app.services.agents.orchestrator import AgentOrchestrator
from app.services.analysis.regime import RegimeDetector
from app.services.consensus.engine import compute_consensus, consensus_evolution
from app.services.etf.engine import ETFIntelligenceEngine
from app.services.global_score.engine import GlobalScoreEngine
from app.services.history.schemas import Timeframe
from app.services.market.repository import MarketRepository
from app.services.memory.engine import MemoryEngine
from app.services.news.repository import NewsRepository
from app.services.portfolio.advisor import PortfolioAdvisorEngine
from app.services.probability.engine import ProbabilityEngine
from app.services.reliability.engine import AgentReliabilityEngine
from app.services.whales.engine import WhaleIntelligenceEngine

_MACRO_SYMBOLS = ("DXY", "GOLD", "SILVER", "OIL", "VIX", "US10Y", "US30Y", "FEDRATE")
_CRYPTO_SYMBOLS = ("BTC", "ETH", "SOL", "TOTAL", "BTC.D")
_NEWS_LOOKBACK_LIMIT = 30
_NEWS_TOP_LIMIT = 5


def _asset_summary(asset: AssetPrice) -> dict:
    return {
        "price": float(asset.price),
        "change_pct_24h": float(asset.change_pct_24h) if asset.change_pct_24h is not None else None,
    }


def _news_summary(items: list[NewsItem]) -> dict:
    counts = {"bullish": 0, "bearish": 0, "neutral": 0}
    for item in items:
        counts[item.sentiment.value] += 1
    top = [
        {"title": item.title, "sentiment": item.sentiment.value, "url": item.url}
        for item in items[:_NEWS_TOP_LIMIT]
    ]
    return {**counts, "top": top}


def diff_snapshots(earlier: MarketSnapshot, later: MarketSnapshot) -> dict:
    """Pure function: two snapshots -> what changed between them. Only
    compares scalar fields that are meaningfully diffable; None on either
    side is reported honestly rather than treated as a 0."""

    def _delta(a: int | None, b: int | None) -> int | None:
        return b - a if a is not None and b is not None else None

    return {
        "earlier_computed_at": earlier.computed_at.isoformat(),
        "later_computed_at": later.computed_at.isoformat(),
        "regime": {
            "from": earlier.regime,
            "to": later.regime,
            "changed": earlier.regime != later.regime,
        },
        "health_score": {
            "from": earlier.health_score,
            "to": later.health_score,
            "delta": _delta(earlier.health_score, later.health_score),
        },
        "trend_strength_score": {
            "from": earlier.trend_strength_score,
            "to": later.trend_strength_score,
            "delta": _delta(earlier.trend_strength_score, later.trend_strength_score),
        },
        "risk_score": {
            "from": earlier.risk_score,
            "to": later.risk_score,
            "delta": _delta(earlier.risk_score, later.risk_score),
        },
        "confidence_score": {
            "from": earlier.confidence_score,
            "to": later.confidence_score,
            "delta": _delta(earlier.confidence_score, later.confidence_score),
        },
        "consensus": {"from": earlier.consensus, "to": later.consensus},
        "consensus_evolution": consensus_evolution(earlier.consensus, later.consensus),
        "portfolio_advice": {"from": earlier.portfolio_advice, "to": later.portfolio_advice},
    }


async def get_latest_consensus(session_factory: async_sessionmaker[AsyncSession]) -> dict | None:
    """The consensus dict from the most recently stored MarketSnapshot,
    without constructing a full MarketReplayEngine (whose constructor needs
    ~10 dependencies unrelated to this one read) -- used by callers that
    only want "what did consensus look like last cycle" for a confidence-
    evolution comparison, e.g. GET /api/consensus."""
    async with session_factory() as session:
        row = await session.scalar(
            select(MarketSnapshot).order_by(MarketSnapshot.computed_at.desc()).limit(1)
        )
    return row.consensus if row is not None else None


async def get_replay_comparison(
    session_factory: async_sessionmaker[AsyncSession], hours_ago: int = 24
) -> dict | None:
    """A Replay-derived "how has the market changed" comparison -- the same
    nearest-snapshot lookup TerminalEngine.compute_historical_comparison()
    uses, exposed as a standalone reader (no MarketReplayEngine
    construction, same rationale as get_latest_consensus() above) so other
    engines can reference Replay's own history without paying its ~10
    write-path dependencies. v9.0 "Reports should reference Replay."
    Returns None when there isn't at least two distinct snapshots to
    compare -- never a fabricated comparison.
    """
    async with session_factory() as session:
        latest = await session.scalar(
            select(MarketSnapshot).order_by(MarketSnapshot.computed_at.desc()).limit(1)
        )
        if latest is None:
            return None
        target_time = latest.computed_at - timedelta(hours=hours_ago)
        earlier = await session.scalar(
            select(MarketSnapshot)
            .where(MarketSnapshot.computed_at <= target_time)
            .order_by(MarketSnapshot.computed_at.desc())
            .limit(1)
        )
        if earlier is None:
            earlier = await session.scalar(
                select(MarketSnapshot)
                .where(MarketSnapshot.computed_at > target_time)
                .order_by(MarketSnapshot.computed_at.asc())
                .limit(1)
            )
    if earlier is None or earlier.id == latest.id:
        return None
    return {"hours_ago": hours_ago, "diff": diff_snapshots(earlier, latest)}


class MarketReplayEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        market_repository: MarketRepository,
        news_repository: NewsRepository,
        regime_detector: RegimeDetector,
        global_score_engine: GlobalScoreEngine,
        agent_orchestrator: AgentOrchestrator,
        reliability_engine: AgentReliabilityEngine,
        portfolio_advisor: PortfolioAdvisorEngine,
        whale_engine: WhaleIntelligenceEngine,
        etf_engine: ETFIntelligenceEngine,
        probability_engine: ProbabilityEngine,
    ) -> None:
        self._session_factory = session_factory
        self._market_repository = market_repository
        self._news_repository = news_repository
        self._regime_detector = regime_detector
        self._global_score_engine = global_score_engine
        self._agent_orchestrator = agent_orchestrator
        self._reliability_engine = reliability_engine
        self._portfolio_advisor = portfolio_advisor
        self._whale_engine = whale_engine
        self._etf_engine = etf_engine
        self._probability_engine = probability_engine

    async def _safe_portfolio_advice(self):
        try:
            return await self._portfolio_advisor.advise("BTC", Timeframe.DAILY)
        except Exception:
            return None

    async def compute_and_store(self) -> MarketSnapshot:
        # Each read below hits a different table/engine and none depends on
        # another's result -- gathering them cuts this cycle's latency to
        # one round-trip's worth instead of N sequential ones.
        assets, regime_snapshot, global_score = await asyncio.gather(
            self._market_repository.get_latest(),
            self._regime_detector.get_latest(),
            self._global_score_engine.get_latest(),
        )
        by_symbol = {a.symbol: a for a in assets}

        agent_outputs = await self._agent_orchestrator.run_all()
        reliability: dict[str, float] | None = None
        try:
            reliability = await self._reliability_engine.evaluate_reliability()
            await self._reliability_engine.log(agent_outputs)
        except Exception:
            reliability = None
        consensus_result = compute_consensus(agent_outputs, reliability)

        (
            portfolio_advice,
            whale_snapshot,
            etf_proxy,
            news_items,
            probability_snapshot,
        ) = await asyncio.gather(
            self._safe_portfolio_advice(),
            self._whale_engine.get_snapshot("BTC"),
            self._etf_engine.get_flow_proxy(),
            self._news_repository.get_recent(limit=_NEWS_LOOKBACK_LIMIT),
            self._probability_engine.get_latest("BTC", Timeframe.DAILY),
        )

        previous = await self.get_latest()
        since = previous.computed_at if previous is not None else None
        memory_engine = MemoryEngine(self._session_factory)
        alerts = await memory_engine.get_category("alerts", limit=50, since=since)

        row = MarketSnapshot(
            regime=regime_snapshot.regime.value if regime_snapshot is not None else None,
            health_score=global_score.global_score if global_score is not None else None,
            trend_strength_score=(
                global_score.trend_strength_score if global_score is not None else None
            ),
            risk_score=global_score.risk_score if global_score is not None else None,
            confidence_score=(global_score.confidence_score if global_score is not None else None),
            consensus=consensus_result.to_dict() if consensus_result is not None else None,
            agents={name: output.to_dict() for name, output in agent_outputs.items()},
            portfolio_advice=portfolio_advice.to_dict() if portfolio_advice is not None else None,
            macro={s: _asset_summary(by_symbol[s]) for s in _MACRO_SYMBOLS if s in by_symbol},
            crypto={s: _asset_summary(by_symbol[s]) for s in _CRYPTO_SYMBOLS if s in by_symbol},
            whale=whale_snapshot,
            etf=etf_proxy,
            news=_news_summary(news_items),
            predictions=(
                {
                    "symbol": probability_snapshot.symbol,
                    "timeframe": probability_snapshot.timeframe.value,
                    "prob_up_pct": probability_snapshot.prob_up_pct,
                    "prob_down_pct": probability_snapshot.prob_down_pct,
                    "prob_flat_pct": probability_snapshot.prob_flat_pct,
                }
                if probability_snapshot is not None
                else None
            ),
            alerts=[entry["summary"] for entry in alerts],
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def get_latest(self) -> MarketSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(MarketSnapshot).order_by(MarketSnapshot.computed_at.desc()).limit(1)
            )

    async def get_nearest(self, timestamp: datetime) -> MarketSnapshot | None:
        """Returns whichever stored snapshot's computed_at is closest to
        `timestamp` -- the one immediately before it, or if none exists,
        the earliest one immediately after."""
        async with self._session_factory() as session:
            before = await session.scalar(
                select(MarketSnapshot)
                .where(MarketSnapshot.computed_at <= timestamp)
                .order_by(MarketSnapshot.computed_at.desc())
                .limit(1)
            )
            if before is not None:
                return before
            return await session.scalar(
                select(MarketSnapshot)
                .where(MarketSnapshot.computed_at > timestamp)
                .order_by(MarketSnapshot.computed_at.asc())
                .limit(1)
            )

    async def get_recent(self, limit: int = 20) -> list[MarketSnapshot]:
        async with self._session_factory() as session:
            rows = list(
                await session.scalars(
                    select(MarketSnapshot).order_by(MarketSnapshot.computed_at.desc()).limit(limit)
                )
            )
        return rows
