from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.database.models import NewsCategory, NewsSentiment
from app.services.agents.crypto_agent import CryptoAgent
from app.services.agents.equity_agent import EquityAgent
from app.services.agents.macro_agent import MacroAgent
from app.services.agents.news_agent import NewsAgent, estimate_impact
from app.services.agents.sentiment_agent import SentimentAgent
from app.services.agents.technical_agent import TechnicalAgent


def test_estimate_impact_high_for_strong_weighted_fed_news():
    assert estimate_impact(sentiment_score=5.0, category="federal_reserve") == "high"


def test_estimate_impact_low_for_weak_crypto_news():
    assert estimate_impact(sentiment_score=1.0, category="crypto") == "low"


def test_estimate_impact_medium_band():
    assert estimate_impact(sentiment_score=2.5, category="crypto") == "medium"


def test_estimate_impact_unknown_category_uses_default_weight():
    assert estimate_impact(sentiment_score=7.0, category="unknown") == "high"


def _global_score(**overrides) -> SimpleNamespace:
    defaults = dict(
        risk_on_score=50,
        risk_off_score=50,
        liquidity_score=50,
        fear_score=50,
        greed_score=50,
        macro_pressure_score=50,
        institutional_activity_score=50,
        crypto_strength_score=50,
        stock_strength_score=50,
        global_score=50,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


async def test_macro_agent_reports_no_direction_when_score_unavailable():
    market_repository = AsyncMock()
    market_repository.get_latest.return_value = []
    global_score_engine = AsyncMock()
    global_score_engine.get_latest.return_value = None

    output = await MacroAgent(market_repository, global_score_engine).summarize()

    assert output.direction is None
    assert output.confidence is None


async def test_macro_agent_bullish_when_risk_on_exceeds_risk_off():
    market_repository = AsyncMock()
    market_repository.get_latest.return_value = []
    global_score_engine = AsyncMock()
    global_score_engine.get_latest.return_value = _global_score(risk_on_score=70, risk_off_score=30)

    output = await MacroAgent(market_repository, global_score_engine).summarize()

    assert output.direction == "bullish"
    assert output.confidence == 40.0


async def test_crypto_agent_direction_follows_crypto_strength_score():
    market_repository = AsyncMock()
    market_repository.get_latest.return_value = []
    global_score_engine = AsyncMock()
    global_score_engine.get_latest.return_value = _global_score(crypto_strength_score=80)
    whale_engine = AsyncMock()
    whale_engine.get_snapshot.return_value = {"available": False, "reason": "no key"}
    etf_engine = AsyncMock()
    etf_engine.get_flow_proxy.return_value = {"available": False, "reason": "no news"}

    output = await CryptoAgent(
        market_repository, global_score_engine, whale_engine, etf_engine
    ).summarize()

    assert output.direction == "bullish"
    assert output.confidence == 60.0


async def test_equity_agent_direction_follows_stock_strength_score():
    market_repository = AsyncMock()
    market_repository.get_latest.return_value = []
    global_score_engine = AsyncMock()
    global_score_engine.get_latest.return_value = _global_score(stock_strength_score=20)

    output = await EquityAgent(market_repository, global_score_engine).summarize()

    assert output.direction == "bearish"
    assert output.confidence == 60.0


async def test_sentiment_agent_direction_follows_global_sentiment_score():
    sentiment_engine = AsyncMock()
    sentiment_engine.compute_and_store.return_value = SimpleNamespace(
        fear_greed_value=65,
        fear_greed_classification="Greed",
        news_sentiment_score=60,
        social_sentiment_available=False,
        social_sentiment_reason="unavailable",
        global_sentiment_score=62,
    )

    output = await SentimentAgent(sentiment_engine).summarize()

    assert output.direction == "bullish"
    assert output.confidence == 24.0


def _news_item(sentiment: NewsSentiment) -> SimpleNamespace:
    return SimpleNamespace(
        title="headline",
        url="https://example.com",
        category=NewsCategory.CRYPTO,
        sentiment=sentiment,
        sentiment_score=1.0,
    )


async def test_news_agent_bullish_when_more_bullish_than_bearish_items():
    news_repository = AsyncMock()
    news_repository.get_recent.return_value = [
        _news_item(NewsSentiment.BULLISH),
        _news_item(NewsSentiment.BULLISH),
        _news_item(NewsSentiment.BEARISH),
        _news_item(NewsSentiment.NEUTRAL),
    ]

    output = await NewsAgent(news_repository).summarize()

    assert output.direction == "bullish"
    assert output.confidence == 25.0


async def test_news_agent_reports_no_direction_when_no_items():
    news_repository = AsyncMock()
    news_repository.get_recent.return_value = []

    output = await NewsAgent(news_repository).summarize()

    assert output.direction is None
    assert output.confidence is None


async def test_sentiment_agent_reports_no_direction_when_global_score_unavailable():
    sentiment_engine = AsyncMock()
    sentiment_engine.compute_and_store.return_value = SimpleNamespace(
        fear_greed_value=None,
        fear_greed_classification=None,
        news_sentiment_score=None,
        social_sentiment_available=False,
        social_sentiment_reason="unavailable",
        global_sentiment_score=None,
    )

    output = await SentimentAgent(sentiment_engine).summarize()

    assert output.direction is None
    assert output.confidence is None


async def test_technical_agent_reports_no_direction_when_analysis_unavailable():
    technical_engine = AsyncMock()
    technical_engine.analyze.return_value = None

    output = await TechnicalAgent(technical_engine).summarize()

    assert output.direction is None
    assert output.confidence is None
    assert output.data["available"] is False


async def test_technical_agent_bullish_when_bullish_score_dominates():
    technical_engine = AsyncMock()
    technical_engine.analyze.return_value = {
        "symbol": "BTC",
        "bullish_score": 90.0,
        "bearish_score": 10.0,
        "trend_strength": 60.0,
        "confidence": 80.0,
        "active_signals": ["RSIOversold", "TechnicalBullish"],
        "high_confidence_alignment": {
            "signal": "HIGH_CONFIDENCE_BUY",
            "reasons": ["RSI oversold", "MACD bullish crossover"],
        },
    }

    output = await TechnicalAgent(technical_engine).summarize()

    assert output.direction == "bullish"
    assert "HIGH_CONFIDENCE_BUY" in output.summary
    assert output.data["available"] is True
