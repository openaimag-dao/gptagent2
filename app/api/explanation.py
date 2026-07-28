from fastapi import APIRouter

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.analysis.regime import RegimeDetector
from app.services.explanation.engine import ExplanationEngine
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.scenarios.engine import ScenarioEngine
from app.services.signals.engine import SignalEngine

router = APIRouter(prefix="/api/explanation", tags=["explanation"])


def _build_engine() -> ExplanationEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    scenario_engine = ScenarioEngine(session_factory, global_score_engine)
    return ExplanationEngine(
        session_factory,
        signal_engine,
        regime_detector,
        news_repository,
        global_score_engine,
        scenario_engine,
    )


@router.get("/{symbol}")
async def get_explanation(symbol: str = "BTC") -> dict:
    engine = _build_engine()
    return await engine.build(symbol)
