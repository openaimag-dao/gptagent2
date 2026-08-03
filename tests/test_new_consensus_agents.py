from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.database.models import PatternSignal
from app.services.agents.correlation_agent import CorrelationAgent
from app.services.agents.onchain_agent import OnchainAgent
from app.services.agents.pattern_agent import PatternAgent, _recency_weighted_direction
from app.services.agents.risk_agent import RiskAgent
from app.services.agents.whale_agent import WhaleAgent


def _global_score(**overrides) -> SimpleNamespace:
    defaults = dict(
        risk_score=50,
        risk_off_score=50,
        fear_score=50,
        macro_pressure_score=50,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _pattern(name: str, direction: str, day: int) -> PatternSignal:
    return PatternSignal(
        symbol="BTC",
        timeframe="daily",
        timestamp=datetime(2026, 8, day, tzinfo=UTC),
        pattern_name=name,
        direction=direction,
    )


# -- WhaleAgent ---------------------------------------------------------------


async def test_whale_agent_reports_no_direction_when_unavailable():
    whale_engine = AsyncMock()
    whale_engine.get_snapshot.return_value = {"available": False, "reason": "no key"}

    output = await WhaleAgent(whale_engine).summarize()

    assert output.direction is None
    assert output.confidence is None
    assert output.data["available"] is False


async def test_whale_agent_bullish_when_long_heavy():
    whale_engine = AsyncMock()
    whale_engine.get_snapshot.return_value = {
        "available": True,
        "classification": "long_heavy",
        "long_short_ratio": 2.0,
        "funding_rate": 0.001,
    }

    output = await WhaleAgent(whale_engine).summarize()

    assert output.direction == "bullish"
    assert output.confidence == 100.0


async def test_whale_agent_neutral_when_balanced():
    whale_engine = AsyncMock()
    whale_engine.get_snapshot.return_value = {
        "available": True,
        "classification": "balanced",
        "long_short_ratio": 1.0,
        "funding_rate": None,
    }

    output = await WhaleAgent(whale_engine).summarize()

    assert output.direction == "neutral"
    assert output.confidence == 0.0


# -- PatternAgent ---------------------------------------------------------------


def test_recency_weighted_direction_empty_is_none():
    assert _recency_weighted_direction([]) == (None, None)


def test_recency_weighted_direction_favors_most_recent():
    signals = [
        _pattern("bullish_engulfing", "bullish", day=5),
        _pattern("death_cross", "bearish", day=3),
        _pattern("golden_cross", "bullish", day=1),
    ]

    direction, confidence = _recency_weighted_direction(signals)

    assert direction == "bullish"
    assert confidence is not None and confidence > 50.0


async def test_pattern_agent_reports_no_direction_when_no_signals():
    pattern_engine = AsyncMock()
    pattern_engine.get_latest.return_value = []

    output = await PatternAgent(pattern_engine).summarize()

    assert output.direction is None
    assert output.confidence is None
    assert output.data["available"] is False


async def test_pattern_agent_bullish_from_real_signals():
    pattern_engine = AsyncMock()
    pattern_engine.get_latest.return_value = [
        _pattern("hammer", "bullish", day=3),
        _pattern("golden_cross", "bullish", day=1),
    ]

    output = await PatternAgent(pattern_engine).summarize()

    assert output.direction == "bullish"
    assert output.data["available"] is True


# -- RiskAgent ------------------------------------------------------------------


async def test_risk_agent_reports_no_direction_when_unavailable():
    global_score_engine = AsyncMock()
    global_score_engine.get_latest.return_value = None

    output = await RiskAgent(global_score_engine).summarize()

    assert output.direction is None
    assert output.confidence is None


async def test_risk_agent_bearish_when_risk_score_high():
    global_score_engine = AsyncMock()
    global_score_engine.get_latest.return_value = _global_score(risk_score=80)

    output = await RiskAgent(global_score_engine).summarize()

    assert output.direction == "bearish"
    assert output.confidence == 60.0


async def test_risk_agent_bullish_when_risk_score_low():
    global_score_engine = AsyncMock()
    global_score_engine.get_latest.return_value = _global_score(risk_score=20)

    output = await RiskAgent(global_score_engine).summarize()

    assert output.direction == "bullish"
    assert output.confidence == 60.0


# -- OnchainAgent ---------------------------------------------------------------


async def test_onchain_agent_always_reports_no_direction():
    onchain_engine = AsyncMock()
    onchain_engine.get_snapshot.return_value = {
        "available": False,
        "reason": "No on-chain data provider configured.",
    }

    output = await OnchainAgent(onchain_engine).summarize()

    assert output.direction is None
    assert output.confidence is None
    assert output.data["available"] is False


# -- CorrelationAgent -------------------------------------------------------------


async def test_correlation_agent_always_reports_no_direction():
    correlation_engine = AsyncMock()
    correlation_engine.get_latest.return_value = [
        SimpleNamespace(symbol_a="BTC", symbol_b="DXY", window_days=30, correlation=-0.6),
    ]

    output = await CorrelationAgent(correlation_engine).summarize()

    assert output.direction is None
    assert output.confidence is None
    assert output.data["available"] is True
    assert output.data["pairs"][0]["correlation"] == -0.6


async def test_correlation_agent_reports_unavailable_when_no_pairs():
    correlation_engine = AsyncMock()
    correlation_engine.get_latest.return_value = []

    output = await CorrelationAgent(correlation_engine).summarize()

    assert output.direction is None
    assert output.data["available"] is False
