from fastapi import APIRouter

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.analysis.regime import RegimeDetector
from app.services.conviction.engine import ConvictionEngine
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.probability.engine import ProbabilityEngine
from app.services.signals.engine import SignalEngine

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("")
async def get_risk() -> dict:
    """Composes the Global Score's already-computed risk-on/off, fear and
    macro-pressure sub-scores with the Signal Engine's conviction tier --
    no new number, just an honest view of already-computed data. Same
    composition /risk in Telegram reports."""
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    conviction_engine = ConvictionEngine(signal_engine, ProbabilityEngine(session_factory))

    global_score = await global_score_engine.get_latest()
    signal_conviction = await conviction_engine.evaluate_signal()

    return {
        "global_score": (
            {
                "risk_off_score": global_score.risk_off_score,
                "risk_on_score": global_score.risk_on_score,
                "fear_score": global_score.fear_score,
                "macro_pressure_score": global_score.macro_pressure_score,
                "risk_score": global_score.risk_score,
                "confidence_score": global_score.confidence_score,
            }
            if global_score is not None
            else None
        ),
        "signal_conviction": signal_conviction,
    }
