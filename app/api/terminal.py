from fastapi import APIRouter, HTTPException, Query

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.agents.orchestrator import build_agent_orchestrator
from app.services.analysis.regime import RegimeDetector
from app.services.breakout.engine import BreakoutEngine
from app.services.committee.engine import CommitteeEngine
from app.services.etf.engine import ETFIntelligenceEngine
from app.services.features.engine import FeatureEngine
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.portfolio.advisor import PortfolioAdvisorEngine
from app.services.portfolio.engine import PortfolioEngine
from app.services.probability.engine import ProbabilityEngine
from app.services.reliability.engine import AgentReliabilityEngine
from app.services.replay.engine import MarketReplayEngine
from app.services.signals.engine import SignalEngine
from app.services.terminal.engine import TerminalEngine
from app.services.whales.engine import WhaleIntelligenceEngine

router = APIRouter(prefix="/api/terminal", tags=["terminal"])


def _build_engine() -> TerminalEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    portfolio_engine = PortfolioEngine(session_factory, market_repository)
    probability_engine = ProbabilityEngine(session_factory)
    portfolio_advisor = PortfolioAdvisorEngine(
        session_factory, signal_engine, probability_engine, portfolio_engine
    )
    feature_engine = FeatureEngine(session_factory, market_repository)
    breakout_engine = BreakoutEngine(session_factory, regime_detector, feature_engine)
    committee_engine = CommitteeEngine(
        build_agent_orchestrator(), AgentReliabilityEngine(session_factory)
    )
    replay_engine = MarketReplayEngine(
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
        probability_engine,
    )
    return TerminalEngine(
        session_factory,
        probability_engine,
        breakout_engine,
        portfolio_advisor,
        portfolio_engine,
        committee_engine,
        global_score_engine,
        replay_engine,
    )


@router.get("/brief")
async def get_brief() -> dict:
    return await _build_engine().compute_brief()


@router.get("/opportunities")
async def get_opportunities() -> dict:
    return {"opportunities": await _build_engine().compute_top_opportunities()}


@router.get("/history")
async def get_history(days: int = Query(7, ge=1, le=365)) -> dict:
    result = await _build_engine().compute_historical_comparison(days_ago=days)
    if result is None:
        raise HTTPException(
            status_code=404, detail=f"No market snapshot old enough to compare {days} days back"
        )
    return result


@router.get("/weekly")
async def get_weekly() -> dict:
    return await _build_engine().compute_period_performance(days=7)


@router.get("/monthly")
async def get_monthly() -> dict:
    return await _build_engine().compute_period_performance(days=30)
