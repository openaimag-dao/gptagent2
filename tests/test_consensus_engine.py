from unittest.mock import AsyncMock

from app.services.agents.base import AgentOutput
from app.services.consensus.engine import ConsensusEngine, compute_consensus, consensus_evolution


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


def test_compute_consensus_exposes_strongest_agent_and_evidence():
    # v8.0: "which engine has the strongest influence" should be real reuse
    # of the same per-agent weight already tallied into the buckets, not a
    # separate calculation, and each agent's own reasoning should be quoted
    # (not just its name) so agree/disagree can be explained.
    outputs = {
        "news": AgentOutput(
            agent="news", summary="*AGENT SUMMARY*\nHeadlines skew risk-on.", direction="bullish",
            confidence=50.0,
        ),
        "macro": AgentOutput(
            agent="macro", summary="*AGENT SUMMARY*\nDXY strength is bearish for risk assets.",
            direction="bearish", confidence=30.0,
        ),
        "equity": AgentOutput(
            agent="equity", summary="*AGENT SUMMARY*\nBreadth confirms the rally.",
            direction="bullish", confidence=20.0,
        ),
    }

    result = compute_consensus(outputs)

    assert result.strongest_agent == "news"  # highest single-agent weight (50/100)
    assert result.agent_weights["news"] == 50.0
    assert result.agent_evidence["news"] == "Headlines skew risk-on."
    assert result.agent_evidence["macro"] == "DXY strength is bearish for risk assets."


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


def test_compute_consensus_scales_weight_by_reliability():
    outputs = {
        "news": _output("news", "bullish", 50.0),
        "macro": _output("macro", "bearish", 50.0),
    }

    # news has a poor track record (20% correct), macro a perfect one (100%)
    result = compute_consensus(outputs, reliability={"news": 20.0, "macro": 100.0})

    # news weight = 50 * 0.2 = 10, macro weight = 50 * 1.0 = 50, total = 60
    assert result.bearish_pct > result.bullish_pct
    assert result.bearish_agents == ["macro"]


def test_compute_consensus_keeps_raw_confidence_for_agents_without_reliability_history():
    outputs = {
        "news": _output("news", "bullish", 50.0),
        "macro": _output("macro", "bearish", 50.0),
    }

    with_reliability = compute_consensus(outputs, reliability={"news": 100.0})
    without_reliability = compute_consensus(outputs, reliability=None)

    # macro isn't in the reliability map, so its weight is unaffected either way
    assert with_reliability.bearish_pct == without_reliability.bearish_pct


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


async def test_consensus_engine_uses_reliability_engine_when_given():
    orchestrator = AsyncMock()
    orchestrator.run_all.return_value = {
        "news": _output("news", "bullish", 50.0),
        "macro": _output("macro", "bearish", 50.0),
    }
    reliability_engine = AsyncMock()
    reliability_engine.evaluate_reliability.return_value = {"news": 20.0, "macro": 100.0}

    result = await ConsensusEngine(orchestrator, reliability_engine).compute()

    reliability_engine.evaluate_reliability.assert_awaited_once()
    reliability_engine.log.assert_awaited_once()
    assert result.bearish_pct > result.bullish_pct


async def test_consensus_engine_survives_reliability_engine_failure():
    orchestrator = AsyncMock()
    orchestrator.run_all.return_value = {"macro": _output("macro", "bullish", 50.0)}
    reliability_engine = AsyncMock()
    reliability_engine.evaluate_reliability.side_effect = RuntimeError("db down")

    result = await ConsensusEngine(orchestrator, reliability_engine).compute()

    assert result.bullish_pct == 100.0


def _consensus_dict(agreement_score, bullish_pct, bearish_pct, strongest_agent):
    return {
        "agreement_score": agreement_score,
        "bullish_pct": bullish_pct,
        "bearish_pct": bearish_pct,
        "strongest_agent": strongest_agent,
    }


def test_consensus_evolution_returns_none_when_either_side_missing():
    later = _consensus_dict(70.0, 70.0, 30.0, "macro")
    assert consensus_evolution(None, later) is None
    assert consensus_evolution(later, None) is None


def test_consensus_evolution_reports_rising_agreement_and_stable_strongest_agent():
    earlier = _consensus_dict(60.0, 60.0, 40.0, "macro")
    later = _consensus_dict(75.0, 75.0, 25.0, "macro")

    evolution = consensus_evolution(earlier, later)

    assert evolution["agreement_score_delta"] == 15.0
    assert evolution["bullish_pct_delta"] == 15.0
    assert evolution["bearish_pct_delta"] == -15.0
    assert evolution["strongest_agent_changed"] is False
    assert "rose +15.0pts" in evolution["summary"]
    assert "macro remains the strongest influence" in evolution["summary"]


def test_consensus_evolution_reports_falling_agreement_and_strongest_agent_shift():
    earlier = _consensus_dict(80.0, 80.0, 20.0, "macro")
    later = _consensus_dict(55.0, 55.0, 45.0, "sentiment")

    evolution = consensus_evolution(earlier, later)

    assert evolution["agreement_score_delta"] == -25.0
    assert evolution["strongest_agent_from"] == "macro"
    assert evolution["strongest_agent_to"] == "sentiment"
    assert evolution["strongest_agent_changed"] is True
    assert "fell -25.0pts" in evolution["summary"]
    assert "shifted from macro to sentiment" in evolution["summary"]


def test_consensus_evolution_reports_unchanged_agreement():
    earlier = _consensus_dict(60.0, 60.0, 40.0, "news")
    later = _consensus_dict(60.0, 60.0, 40.0, "news")

    evolution = consensus_evolution(earlier, later)

    assert evolution["agreement_score_delta"] == 0.0
    assert "unchanged" in evolution["summary"]
