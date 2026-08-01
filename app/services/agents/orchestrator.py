import asyncio

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.agents.base import AgentOutput
from app.services.agents.crypto_agent import CryptoAgent
from app.services.agents.equity_agent import EquityAgent
from app.services.agents.macro_agent import MacroAgent
from app.services.agents.news_agent import NewsAgent
from app.services.agents.sentiment_agent import SentimentAgent
from app.services.agents.technical_agent import TechnicalAgent
from app.services.analysis.regime import RegimeDetector
from app.services.etf.engine import ETFIntelligenceEngine
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.sentiment.engine import SentimentEngine
from app.services.signals.engine import SignalEngine
from app.services.technical.engine import TechnicalAnalysisEngine
from app.services.technical.provider import TechnicalAnalysisProvider
from app.services.whales.engine import WhaleIntelligenceEngine


class AgentOrchestrator:
    """Runs every specialist agent concurrently and returns their outputs
    keyed by name -- the shared input the Reasoning Agent (ReportGenerator)
    synthesizes into one institutional narrative."""

    def __init__(
        self,
        macro_agent: MacroAgent,
        crypto_agent: CryptoAgent,
        equity_agent: EquityAgent,
        news_agent: NewsAgent,
        sentiment_agent: SentimentAgent,
        technical_agent: TechnicalAgent,
    ) -> None:
        self._macro_agent = macro_agent
        self._crypto_agent = crypto_agent
        self._equity_agent = equity_agent
        self._news_agent = news_agent
        self._sentiment_agent = sentiment_agent
        self._technical_agent = technical_agent

    async def run_all(self) -> dict[str, AgentOutput]:
        macro, crypto, equity, news, sentiment, technical = await asyncio.gather(
            self._macro_agent.summarize(),
            self._crypto_agent.summarize(),
            self._equity_agent.summarize(),
            self._news_agent.summarize(),
            self._sentiment_agent.summarize(),
            self._technical_agent.summarize(),
        )
        return {
            "macro": macro,
            "crypto": crypto,
            "equity": equity,
            "news": news,
            "sentiment": sentiment,
            "technical": technical,
        }


def build_agent_orchestrator() -> AgentOrchestrator:
    """Wires every agent from the same repositories/engines already used
    elsewhere (build_report_generator, /api/global-score, ...) -- no second
    set of connections or duplicated construction logic."""
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    whale_engine = WhaleIntelligenceEngine()
    etf_engine = ETFIntelligenceEngine(news_repository)
    sentiment_engine = SentimentEngine(session_factory, news_repository)
    technical_engine = TechnicalAnalysisEngine(
        session_factory, TechnicalAnalysisProvider(session_factory)
    )

    return AgentOrchestrator(
        macro_agent=MacroAgent(market_repository, global_score_engine),
        crypto_agent=CryptoAgent(market_repository, global_score_engine, whale_engine, etf_engine),
        equity_agent=EquityAgent(market_repository, global_score_engine),
        news_agent=NewsAgent(news_repository),
        sentiment_agent=SentimentAgent(sentiment_engine),
        technical_agent=TechnicalAgent(technical_engine),
    )
