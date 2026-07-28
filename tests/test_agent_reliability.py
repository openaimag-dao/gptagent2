from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.agents.base import AgentOutput
from app.services.reliability.engine import AgentReliabilityEngine


def _row(timestamp, close):
    return SimpleNamespace(timestamp=timestamp, close=close)


def _log(agent, direction, reference_timestamp, horizon_periods=1):
    return SimpleNamespace(
        agent=agent,
        direction=direction,
        reference_timestamp=reference_timestamp,
        horizon_periods=horizon_periods,
    )


async def test_log_persists_only_agents_with_a_direction():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [_row(t0, 100.0)]
    outputs = {
        "macro": AgentOutput(agent="macro", summary="", direction="bullish", confidence=60.0),
        "crypto": AgentOutput(agent="crypto", summary="", direction=None, confidence=None),
    }

    session = AsyncMock()
    session.add_all = MagicMock()
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=rows)):
        engine = AgentReliabilityEngine(session_factory)
        await engine.log(outputs)

    session.add_all.assert_called_once()
    (persisted,), _ = session.add_all.call_args
    assert len(persisted) == 1
    assert persisted[0].agent == "macro"
    assert persisted[0].reference_timestamp == t0


async def test_log_no_op_when_no_history_synced_yet():
    session_factory = AsyncMock()
    outputs = {"macro": AgentOutput(agent="macro", summary="", direction="bullish")}

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=[])):
        engine = AgentReliabilityEngine(session_factory)
        await engine.log(outputs)

    session_factory.assert_not_called()


async def test_evaluate_reliability_scores_correct_and_incorrect_calls():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    rows = [_row(t0, 100.0), _row(t1, 110.0)]  # +10% -> realized "up"

    logs = [
        _log("macro", "bullish", t0),  # predicted up -> correct
        _log("crypto", "bearish", t0),  # predicted down -> incorrect
    ]

    session = AsyncMock()
    session.scalars.return_value = logs
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=rows)):
        engine = AgentReliabilityEngine(session_factory)
        result = await engine.evaluate_reliability()

    assert result == {"macro": 100.0, "crypto": 0.0}


async def test_evaluate_reliability_skips_predictions_whose_horizon_has_not_elapsed():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [_row(t0, 100.0)]  # no target_idx exists yet
    logs = [_log("macro", "bullish", t0)]

    session = AsyncMock()
    session.scalars.return_value = logs
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=rows)):
        engine = AgentReliabilityEngine(session_factory)
        result = await engine.evaluate_reliability()

    assert result == {}


async def test_evaluate_reliability_empty_without_synced_history():
    session_factory = AsyncMock()

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=[])):
        engine = AgentReliabilityEngine(session_factory)
        result = await engine.evaluate_reliability()

    assert result == {}
