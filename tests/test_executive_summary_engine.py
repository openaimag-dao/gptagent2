from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.executive_summary.engine import (
    ExecutiveSummaryEngine,
    classify_ai_action,
    compose_market_factors,
    compose_summary,
)

# -- compose_market_factors -------------------------------------------------


def test_compose_market_factors_maps_active_signals():
    bullish, bearish = compose_market_factors(
        ["RSIOverbought", "GoldenCross", "TrendWeakening"], None, None, None, None, None
    )
    assert "Overbought RSI" in bearish
    assert "Golden Cross (SMA50 crossed above SMA200)" in bullish
    assert "Trend weakening" in bearish


def test_compose_market_factors_ignores_unknown_signals():
    bullish, bearish = compose_market_factors(["SomeUnknownSignal"], None, None, None, None, None)
    assert bullish == []
    assert bearish == []


def test_compose_market_factors_consensus_agents():
    consensus = {
        "bullish_agents": ["technical_agent"],
        "bearish_agents": ["sentiment_agent"],
        "agent_evidence": {"technical_agent": "Strong uptrend", "sentiment_agent": "Fear rising"},
    }
    bullish, bearish = compose_market_factors(None, consensus, None, None, None, None)
    assert bullish == ["Technical Agent: Strong uptrend"]
    assert bearish == ["Sentiment Agent: Fear rising"]


def test_compose_market_factors_supporting_news():
    news = [
        {"title": "ETF approved", "sentiment": "bullish"},
        {"title": "Regulator crackdown", "sentiment": "bearish"},
        {"title": "Nothing notable", "sentiment": "neutral"},
    ]
    bullish, bearish = compose_market_factors(None, None, news, None, None, None)
    assert bullish == ["Positive news: ETF approved"]
    assert bearish == ["Negative news: Regulator crackdown"]


def test_compose_market_factors_fear_greed():
    bullish, _ = compose_market_factors(None, None, None, "Greed", None, None)
    assert "Crypto Fear & Greed: Greed" in bullish
    _, bearish = compose_market_factors(None, None, None, "Extreme Fear", None, None)
    assert "Crypto Fear & Greed: Extreme Fear" in bearish
    bullish, bearish = compose_market_factors(None, None, None, "Neutral", None, None)
    assert bullish == []
    assert bearish == []


def test_compose_market_factors_etf_proxy():
    proxy = {"available": True, "classification": "leaning_institutional_buying"}
    bullish, _ = compose_market_factors(None, None, None, None, proxy, None)
    assert any("institutional buying" in f for f in bullish)

    proxy_unavailable = {"available": False}
    bullish, bearish = compose_market_factors(None, None, None, None, proxy_unavailable, None)
    assert bullish == []
    assert bearish == []


def test_compose_market_factors_whale_funding():
    healthy = {"available": True, "funding_rate": 0.00001}
    bullish, _ = compose_market_factors(None, None, None, None, None, healthy)
    assert any("Healthy funding rate" in f for f in bullish)

    extreme = {"available": True, "funding_rate": 0.001}
    _, bearish = compose_market_factors(None, None, None, None, None, extreme)
    assert any("Extreme funding rate" in f for f in bearish)

    unavailable = {"available": False}
    bullish, bearish = compose_market_factors(None, None, None, None, None, unavailable)
    assert bullish == []
    assert bearish == []


# -- classify_ai_action ------------------------------------------------------


def test_classify_ai_action_no_committee_data():
    action, reason = classify_ai_action(None, None, None)
    assert action == "No Trade"
    assert "Insufficient" in reason


def test_classify_ai_action_strong_buy():
    action, _ = classify_ai_action("BUY", 85.0, 30)
    assert action == "Strong Buy"


def test_classify_ai_action_buy():
    action, _ = classify_ai_action("BUY", 65.0, 30)
    assert action == "Buy"


def test_classify_ai_action_accumulate():
    action, _ = classify_ai_action("BUY", 45.0, 30)
    assert action == "Accumulate"


def test_classify_ai_action_reduce_risk_on_high_risk_sell():
    action, reason = classify_ai_action("SELL", 55.0, 80)
    assert action == "Reduce Risk"
    assert "80/100" in reason


def test_classify_ai_action_sell():
    action, _ = classify_ai_action("SELL", 85.0, 30)
    assert action == "Sell"


def test_classify_ai_action_take_profit():
    action, _ = classify_ai_action("SELL", 55.0, 30)
    assert action == "Take Profit"


def test_classify_ai_action_hold():
    action, _ = classify_ai_action("HOLD", 50.0, 30)
    assert action == "Hold"


def test_classify_ai_action_no_trade_on_low_confidence_hold():
    action, _ = classify_ai_action("HOLD", 20.0, 30)
    assert action == "No Trade"


def test_classify_ai_action_missing_risk_defaults_to_neutral():
    # A None risk_score should never block a real BUY/SELL decision from resolving.
    action, _ = classify_ai_action("SELL", 55.0, None)
    assert action == "Take Profit"


# -- compose_summary ----------------------------------------------------------


def test_compose_summary_produces_3_to_5_sentences():
    summary = compose_summary(
        "Bullish", 62, "Trending", 45.0, 70, "Moderate", 40, "Buy", "Because reasons."
    )
    sentence_count = summary.count(". ") + 1
    assert 3 <= sentence_count <= 5
    assert "62/100" in summary
    assert "Buy" in summary


def test_compose_summary_handles_missing_data_honestly():
    summary = compose_summary(
        "Neutral", None, "Range", None, None, "Unknown", None, "No Trade", "No data."
    )
    assert "volatility data unavailable" in summary
    assert "The market is neutral." in summary


# -- ExecutiveSummaryEngine.compute -------------------------------------------


def _session_factory(watchdog=None):
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=watchdog)
    session.__aenter__.return_value = session
    return MagicMock(return_value=session)


def _build_engine(watchdog=None):
    session_factory = _session_factory(watchdog)
    deps = {
        "global_score_engine": AsyncMock(),
        "technical_engine": AsyncMock(),
        "sentiment_engine": AsyncMock(),
        "explanation_engine": AsyncMock(),
        "whale_engine": AsyncMock(),
        "onchain_engine": AsyncMock(),
        "etf_engine": AsyncMock(),
    }
    engine = ExecutiveSummaryEngine(
        session_factory,
        deps["global_score_engine"],
        deps["technical_engine"],
        deps["sentiment_engine"],
        deps["explanation_engine"],
        deps["whale_engine"],
        deps["onchain_engine"],
        deps["etf_engine"],
    )
    return engine, deps


async def test_compute_returns_none_without_watchdog_snapshot():
    engine, _ = _build_engine(watchdog=None)
    assert await engine.compute("BTC") is None


async def test_compute_builds_full_payload():
    watchdog = SimpleNamespace(
        global_score=62,
        liquidity_score=55,
        risk_score=40,
        volatility=35.0,
        regime="accumulation",
        consensus={
            "bullish_pct": 60.0,
            "bearish_pct": 20.0,
            "neutral_pct": 20.0,
            "bullish_agents": ["technical_agent"],
            "bearish_agents": [],
            "agent_evidence": {"technical_agent": "Strong uptrend"},
        },
        committee_decision="BUY",
        committee_confidence_pct=75.0,
        computed_at=datetime(2026, 8, 3, tzinfo=UTC),
    )
    engine, deps = _build_engine(watchdog=watchdog)
    deps["global_score_engine"].get_latest.return_value = SimpleNamespace(
        institutional_activity_score=65
    )
    deps["technical_engine"].get_latest.return_value = SimpleNamespace(
        trend_strength=45.0, active_signals=["GoldenCross"]
    )
    deps["sentiment_engine"].get_latest.return_value = SimpleNamespace(
        global_sentiment_score=70, news_sentiment_score=65, fear_greed_classification="Greed"
    )
    deps["explanation_engine"].build.return_value = {"supporting_news": []}
    deps["whale_engine"].get_snapshot.return_value = {"available": False}
    deps["onchain_engine"].get_snapshot.return_value = {"available": False, "metrics": {}}
    deps["etf_engine"].get_flow_proxy.return_value = {"available": False}

    payload = await engine.compute("BTC")

    assert payload["symbol"] == "BTC"
    assert payload["overall_score"] == 62
    assert payload["bias"] == "Strong Bullish"
    assert payload["action"] == "Buy"
    assert "Technical Agent: Strong uptrend" in payload["bullish_factors"]
    assert "Golden Cross (SMA50 crossed above SMA200)" in payload["bullish_factors"]
    assert payload["market_health"]["liquidity"] == 55
    assert payload["market_health"]["institutional_activity"] == 65
    assert payload["market_health"]["onchain_activity"] is None
    assert payload["market_health"]["news_quality"] == 65
    assert "Buy" in payload["summary"]
