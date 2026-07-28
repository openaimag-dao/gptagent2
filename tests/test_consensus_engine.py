from unittest.mock import AsyncMock

from app.services.agents.base import AgentOutput
from app.services.consensus.engine import ConsensusEngine, compute_consensus


def _output(agent: str, direction: str | None, confidence: float | None) -> AgentOutput:
    return AgentOutput(agent=agent, summary="", direction=direction, confidence=confidence)


def test_compute_consensus_returns_none_when_no_agent_reports():
    outputs = {
        "macro": _output("macro", None, None),
        "crypto": _output("crypto", None, None),
    }

    assert compute_consensus(outputs) is None


def test_compute_consensus_unanimous_bullish_is_100_percent():
    outputs = {
        "macro": _output("macro", "bullish", 40.0),
        "crypto": _output("crypto", "bullish", 60.0),
    }

    result = compute_consensus(outputs)

    assert result.bullish_pct == 100.0
    assert result.bearish_pct == 0.0
    assert result.neutral_pct == 0.0
    assert result.agreement_score == 100.0
    assert result.conflict_pct == 0.0
    assert result.bullish_agents == ["macro", "crypto"]


def test_compute_consensus_splits_by_confidence_weighted_vote():
    outputs = {
        "news": _output("news", "bullish", 50.0),
        "macro": _output("macro", "bearish", 30.0),
        "equity": _output("equity", "bullish", 20.0),
    }

    result = compute_consensus(outputs)

    # bullish weight = 50 + 20 = 70, bearish weight = 30, total = 100
    assert result.bullish_pct == 70.0
    assert result.bearish_pct == 30.0
    assert result.neutral_pct == 0.0
    assert result.agreement_score == 70.0
    assert result.conflict_pct == 30.0
    assert set(result.bullish_agents) == {"news", "equity"}
    assert result.bearish_agents == ["macro"]


def test_compute_consensus_excludes_unavailable_agents_from_the_tally():
    outputs = {
        "macro": _output("macro", None, None),
        "crypto": _output("crypto", "bullish", 50.0),
    }

    result = compute_consensus(outputs)

    assert result.bullish_pct == 100.0
    assert result.unavailable_agents == ["macro"]
    assert "macro" not in result.bullish_agents


def test_compute_consensus_floors_zero_confidence_votes_so_they_still_count():
    outputs = {
        "macro": _output("macro", "neutral", 0.0),
        "crypto": _output("crypto", "neutral", 0.0),
    }

    result = compute_consensus(outputs)

    assert result.neutral_pct == 100.0
    assert result.neutral_agents == ["macro", "crypto"]


def test_compute_consensus_percentages_always_sum_to_100():
    outputs = {
        "a": _output("a", "bullish", 33.0),
        "b": _output("b", "bearish", 33.0),
        "c": _output("c", "neutral", 34.0),
    }

    result = compute_consensus(outputs)

    total = result.bullish_pct + result.bearish_pct + result.neutral_pct
    assert total == 100.0


async def test_consensus_engine_runs_orchestrator_and_tallies_the_result():
    orchestrator = AsyncMock()
    orchestrator.run_all.return_value = {
        "macro": _output("macro", "bullish", 50.0),
        "crypto": _output("crypto", "bullish", 50.0),
    }

    result = await ConsensusEngine(orchestrator).compute()

    orchestrator.run_all.assert_awaited_once()
    assert result.bullish_pct == 100.0


async def test_consensus_engine_returns_none_when_nothing_to_tally():
    orchestrator = AsyncMock()
    orchestrator.run_all.return_value = {"macro": _output("macro", None, None)}

    result = await ConsensusEngine(orchestrator).compute()

    assert result is None
