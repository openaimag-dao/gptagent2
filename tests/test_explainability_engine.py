from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.explainability.engine import (
    EngineBreakdownRow,
    ExplainabilityEngine,
    _agent_explanation,
    _agent_signal,
    _agent_weight,
    _compose_summary_text,
    _correlation_explanation,
    _historical_confidence,
    _historical_signal_and_explanation,
    _pattern_explanation,
    _whale_explanation,
)

# -- pure helpers -------------------------------------------------------------


def test_agent_signal_bullish_bearish_neutral_unavailable():
    consensus = {
        "bullish_agents": ["technical"],
        "bearish_agents": ["news"],
        "neutral_agents": ["sentiment"],
        "unavailable_agents": ["macro"],
    }
    assert _agent_signal("technical", consensus) == "Bullish"
    assert _agent_signal("news", consensus) == "Bearish"
    assert _agent_signal("sentiment", consensus) == "Neutral"
    assert _agent_signal("macro", consensus) is None
    assert _agent_signal("technical", None) is None


def test_agent_explanation_strips_leading_marker():
    consensus = {"agent_evidence": {"technical": "- BTC: 62,000 (+1.2% 24h)"}}
    assert _agent_explanation("technical", consensus) == "BTC: 62,000 (+1.2% 24h)"
    assert _agent_explanation("news", consensus) is None
    assert _agent_explanation("technical", None) is None


def test_agent_weight_reads_consensus_share():
    consensus = {"agent_weights": {"technical": 42.5}}
    assert _agent_weight("technical", consensus) == 42.5
    assert _agent_weight("news", consensus) is None
    assert _agent_weight("technical", None) is None


def test_whale_explanation_available():
    snapshot = {
        "available": True,
        "classification": "long_heavy",
        "long_short_ratio": 1.35,
        "funding_rate": 0.0002,
    }
    explanation = _whale_explanation(snapshot)
    assert "long heavy" in explanation
    assert "1.35" in explanation
    assert "0.02" in explanation or "0.0200%" in explanation


def test_whale_explanation_unavailable():
    snapshot = {"available": False, "reason": "CoinGlass returned no usable data"}
    assert (
        _whale_explanation(snapshot) == "Unavailable this cycle: CoinGlass returned no usable data"
    )


def test_correlation_explanation_sorts_by_magnitude():
    correlations = [
        SimpleNamespace(symbol_a="BTC", symbol_b="SPX", window_days=30, correlation=0.2),
        SimpleNamespace(symbol_a="BTC", symbol_b="DXY", window_days=30, correlation=-0.8),
        SimpleNamespace(symbol_a="ETH", symbol_b="BTC", window_days=7, correlation=0.9),
    ]
    result = _correlation_explanation(correlations, "BTC")
    assert result is not None
    assert "BTC-DXY: -0.80" in result
    assert "BTC-SPX: +0.20" in result
    assert "ETH" not in result  # wrong window, excluded


def test_correlation_explanation_none_when_no_matches():
    assert _correlation_explanation([], "BTC") is None


def test_historical_signal_and_explanation_empty():
    signal, explanation = _historical_signal_and_explanation([])
    assert signal is None
    assert explanation == "No similar historical periods found yet."


def test_historical_signal_and_explanation_bullish():
    examples = [
        {
            "match_timestamp": "2024-01-01T00:00:00+00:00",
            "similarity_score": 92.0,
            "regime": "accumulation",
            "forward_return_7d_pct": 5.0,
        },
        {
            "match_timestamp": "2024-02-01T00:00:00+00:00",
            "similarity_score": 80.0,
            "regime": "accumulation",
            "forward_return_7d_pct": 3.0,
        },
    ]
    signal, explanation = _historical_signal_and_explanation(examples)
    assert signal == "Bullish"
    assert "2 similar historical periods" in explanation
    assert "92% similar" in explanation
    assert "+4.00%" in explanation


def test_historical_confidence_averages_similarity():
    examples = [{"similarity_score": 80.0}, {"similarity_score": 60.0}]
    assert _historical_confidence(examples) == 70
    assert _historical_confidence([]) is None


def _pattern_signal(name: str, direction: str, day: int) -> SimpleNamespace:
    return SimpleNamespace(
        pattern_name=name, direction=direction, timestamp=datetime(2026, 1, day, tzinfo=UTC)
    )


def test_pattern_explanation_empty():
    assert _pattern_explanation([]) == "No patterns detected in recent history."


def test_pattern_explanation_lists_recent_patterns():
    signals = [
        _pattern_signal("golden_cross", "bullish", 5),
        _pattern_signal("hammer", "bullish", 3),
    ]
    explanation = _pattern_explanation(signals)
    assert "golden_cross (bullish)" in explanation
    assert "hammer (bullish)" in explanation


def test_compose_summary_text_no_signals():
    assert _compose_summary_text(None, None, []) == (
        "Not enough engines reported a signal this cycle to form a consensus view."
    )


def test_compose_summary_text_names_strongest_row():
    rows = [
        EngineBreakdownRow("Technical Analysis", "Bullish", 80, 60.0, "Strong uptrend"),
        EngineBreakdownRow("News", "Bullish", 40, 10.0, "Positive coverage"),
    ]
    consensus = {"agreement_score": 70.0}
    summary = _compose_summary_text("Strong Bullish", consensus, rows)
    assert "2 of 2 engines" in summary
    assert "Strong Bullish" in summary
    assert "70.0% agreement" in summary
    assert "Technical Analysis carries the most weight (60.0%)" in summary
    assert "Strong uptrend" in summary


# -- ExplainabilityEngine.build ------------------------------------------------


def _session_factory(watchdog=None):
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=watchdog)
    session.__aenter__.return_value = session
    return MagicMock(return_value=session)


def _build_engine(watchdog=None):
    session_factory = _session_factory(watchdog)
    deps = {
        "explanation_engine": AsyncMock(),
        "global_score_engine": AsyncMock(),
        "technical_engine": AsyncMock(),
        "sentiment_engine": AsyncMock(),
        "correlation_engine": AsyncMock(),
        "whale_engine": AsyncMock(),
        "onchain_engine": AsyncMock(),
        "pattern_engine": AsyncMock(),
    }
    deps["pattern_engine"].get_latest.return_value = []
    engine = ExplainabilityEngine(
        session_factory,
        deps["explanation_engine"],
        deps["global_score_engine"],
        deps["technical_engine"],
        deps["sentiment_engine"],
        deps["correlation_engine"],
        deps["whale_engine"],
        deps["onchain_engine"],
        deps["pattern_engine"],
    )
    return engine, deps


async def test_build_returns_explanation_plus_breakdown_without_watchdog():
    engine, deps = _build_engine(watchdog=None)
    deps["explanation_engine"].build.return_value = {"symbol": "BTC", "historical_examples": []}
    deps["global_score_engine"].get_latest.return_value = None
    deps["technical_engine"].get_latest.return_value = None
    deps["sentiment_engine"].get_latest.return_value = None
    deps["correlation_engine"].get_latest.return_value = []
    deps["whale_engine"].get_snapshot.return_value = {"available": False, "reason": "no data"}
    deps["onchain_engine"].get_snapshot.return_value = {"available": False, "metrics": {}}

    result = await engine.build("BTC")

    assert result["symbol"] == "BTC"
    assert len(result["engine_breakdown"]) == 9
    names = [row["name"] for row in result["engine_breakdown"]]
    assert names == [
        "Technical Analysis",
        "News",
        "Sentiment",
        "Macro",
        "On-chain",
        "Whales",
        "Correlations",
        "Pattern",
        "Historical Patterns",
    ]
    assert result["final_prediction"]["bias"] is None
    assert result["final_prediction"]["committee_decision"] is None
    assert "Not enough engines" in result["summary_text"]


async def test_build_full_payload_with_watchdog_consensus():
    watchdog = SimpleNamespace(
        consensus={
            "bullish_pct": 65.0,
            "bearish_pct": 15.0,
            "neutral_pct": 20.0,
            "agreement_score": 65.0,
            "bullish_agents": ["technical", "news", "whale", "pattern", "historical"],
            "bearish_agents": [],
            "neutral_agents": ["sentiment", "macro"],
            "unavailable_agents": [],
            "agent_weights": {
                "technical": 40.0,
                "news": 30.0,
                "sentiment": 20.0,
                "macro": 10.0,
                "whale": 5.0,
                "pattern": 5.0,
                "historical": 5.0,
            },
            "agent_evidence": {"technical": "Strong uptrend", "news": "Positive coverage"},
        },
        committee_decision="BUY",
        committee_recommendation="BUY (high conviction)",
    )
    engine, deps = _build_engine(watchdog=watchdog)
    deps["explanation_engine"].build.return_value = {
        "symbol": "BTC",
        "historical_examples": [
            {
                "match_timestamp": "2024-01-01T00:00:00+00:00",
                "similarity_score": 90.0,
                "regime": "accumulation",
                "forward_return_7d_pct": 4.0,
            }
        ],
    }
    deps["global_score_engine"].get_latest.return_value = SimpleNamespace(macro_pressure_score=70)
    deps["technical_engine"].get_latest.return_value = SimpleNamespace(confidence=80.0)
    deps["sentiment_engine"].get_latest.return_value = SimpleNamespace(
        news_sentiment_score=60, global_sentiment_score=55
    )
    deps["correlation_engine"].get_latest.return_value = []
    deps["whale_engine"].get_snapshot.return_value = {"available": False, "reason": "no data"}
    deps["onchain_engine"].get_snapshot.return_value = {"available": False, "metrics": {}}
    deps["pattern_engine"].get_latest.return_value = [_pattern_signal("golden_cross", "bullish", 5)]

    result = await engine.build("BTC")

    breakdown = {row["name"]: row for row in result["engine_breakdown"]}
    assert breakdown["Technical Analysis"]["signal"] == "Bullish"
    assert breakdown["Technical Analysis"]["confidence"] == 80
    assert breakdown["Technical Analysis"]["weight"] == 40.0
    assert breakdown["Technical Analysis"]["explanation"] == "Strong uptrend"
    assert breakdown["News"]["signal"] == "Bullish"
    assert breakdown["Sentiment"]["signal"] == "Neutral"
    assert breakdown["Macro"]["weight"] == 10.0
    assert breakdown["Whales"]["signal"] == "Bullish"
    assert breakdown["Whales"]["weight"] == 5.0
    assert breakdown["Pattern"]["signal"] == "Bullish"
    assert breakdown["Pattern"]["weight"] == 5.0
    assert "golden_cross" in breakdown["Pattern"]["explanation"]
    assert breakdown["Historical Patterns"]["signal"] == "Bullish"
    assert breakdown["Historical Patterns"]["weight"] == 5.0

    assert result["final_prediction"]["bias"] == "Strong Bullish"
    assert result["final_prediction"]["committee_decision"] == "BUY"
    # On-chain and Correlations have no agent key mapping (signal stays
    # None); the other 7 rows all got a real consensus bucket.
    assert "7 of 9 engines" in result["summary_text"]
    assert "Technical Analysis carries the most weight (40.0%)" in result["summary_text"]
