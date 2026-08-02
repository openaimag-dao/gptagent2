from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from app.database.models import CryptoHistory, MarketSnapshot
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.agents.orchestrator import build_agent_orchestrator
from app.services.analysis.regime import RegimeDetector
from app.services.etf.engine import ETFIntelligenceEngine
from app.services.global_score.engine import GlobalScoreEngine
from app.services.history.schemas import Timeframe
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.portfolio.advisor import PortfolioAdvisorEngine
from app.services.portfolio.engine import PortfolioEngine
from app.services.probability.engine import ProbabilityEngine
from app.services.reliability.engine import AgentReliabilityEngine
from app.services.replay.engine import (
    MarketReplayEngine,
    build_replay_insight,
    committee_from_snapshot,
    diff_snapshots,
)
from app.services.signals.engine import SignalEngine
from app.services.similar_market.engine import SimilarMarketEngine, build_historical_lesson
from app.services.whales.engine import WhaleIntelligenceEngine

# BTC is the established codebase convention for "the symbol standing in for
# overall market conditions" when a whole-market context (not a single-
# symbol screen) needs a historical-similarity read -- same choice
# CriticalAlertEngine/TerminalEngine already make (app/services/shocks/
# engine.py's _SIMILARITY_SYMBOLS, app/services/terminal/engine.py's
# _OPPORTUNITY_SYMBOLS).
_MARKET_PROXY_SYMBOL = "BTC"

router = APIRouter(prefix="/api/replay", tags=["replay"])


def _build_engine() -> MarketReplayEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    portfolio_engine = PortfolioEngine(session_factory, market_repository)
    portfolio_advisor = PortfolioAdvisorEngine(
        session_factory, signal_engine, ProbabilityEngine(session_factory), portfolio_engine
    )
    return MarketReplayEngine(
        session_factory,
        market_repository,
        news_repository,
        regime_detector,
        global_score_engine,
        build_agent_orchestrator(),
        AgentReliabilityEngine(session_factory),
        portfolio_advisor,
        WhaleIntelligenceEngine(session_factory),
        ETFIntelligenceEngine(news_repository, session_factory),
        ProbabilityEngine(session_factory),
    )


def _serialize(row: MarketSnapshot) -> dict:
    return {
        "regime": row.regime,
        "health_score": row.health_score,
        "trend_strength_score": row.trend_strength_score,
        "risk_score": row.risk_score,
        "confidence_score": row.confidence_score,
        "consensus": row.consensus,
        "agents": row.agents,
        "portfolio_advice": row.portfolio_advice,
        "macro": row.macro,
        "crypto": row.crypto,
        "whale": row.whale,
        "etf": row.etf,
        "news": row.news,
        "predictions": row.predictions,
        "alerts": row.alerts,
        "computed_at": row.computed_at.isoformat(),
    }


@router.get("")
async def get_replay(limit: int = Query(1, ge=1, le=100)) -> dict:
    engine = _build_engine()
    rows = await engine.get_recent(limit=limit)
    if not rows:
        raise HTTPException(status_code=503, detail="No market snapshot has been taken yet")
    return {"count": len(rows), "snapshots": [_serialize(r) for r in rows]}


@router.get("/compare")
async def compare_replay(t1: datetime = Query(...), t2: datetime = Query(...)) -> dict:
    engine = _build_engine()
    row1 = await engine.get_nearest(t1)
    row2 = await engine.get_nearest(t2)
    if row1 is None or row2 is None:
        raise HTTPException(
            status_code=404, detail="No snapshot found near one or both requested timestamps"
        )
    earlier, later = (row1, row2) if row1.computed_at <= row2.computed_at else (row2, row1)
    return diff_snapshots(earlier, later)


@router.get("/insight")
async def get_replay_insight() -> dict:
    """v10.0 AI Insight block for the latest snapshot -- composes the
    already-persisted regime/scores/consensus with a reconstructed
    historical Committee verdict (committee_from_snapshot(), no new
    engine/column) and a BTC-proxy historical-similarity read
    (SimilarMarketEngine, the same market-proxy convention
    CriticalAlertEngine/TerminalEngine already use)."""
    engine = _build_engine()
    row = await engine.get_latest()
    if row is None:
        raise HTTPException(status_code=503, detail="No market snapshot has been taken yet")

    committee = committee_from_snapshot(row)

    session_factory = get_session_factory()
    try:
        matches = await SimilarMarketEngine(session_factory).find_similar_periods(
            _MARKET_PROXY_SYMBOL, CryptoHistory, Timeframe.DAILY
        )
    except Exception:
        matches = []
    historical_lesson = build_historical_lesson(_MARKET_PROXY_SYMBOL, matches)

    return build_replay_insight(row, committee, historical_lesson)


@router.get("/{timestamp}")
async def get_replay_at(timestamp: datetime) -> dict:
    engine = _build_engine()
    row = await engine.get_nearest(timestamp)
    if row is None:
        raise HTTPException(status_code=404, detail="No snapshot found near that timestamp")
    return _serialize(row)
