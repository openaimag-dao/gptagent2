from unittest.mock import AsyncMock

from app.services.agents.base import AgentOutput
from app.services.committee.engine import CommitteeEngine, convene_committee
from app.services.consensus.engine import ConsensusResult


def _output(
    agent: str, direction: str | None, confidence: float | None, summary: str
) -> AgentOutput:
    return AgentOutput(agent=agent, summary=summary, direction=direction, confidence=confidence)


def test_unanimous_bullish_gives_buy_with_no_dissent():
    agent_outputs = {
        "macro": _output("macro", "bullish", 80.0, "DXY falling, liquidity expanding."),
        "crypto": _output("crypto", "bullish", 70.0, "BTC above all key moving averages."),
    }
    consensus = ConsensusResult(
        bullish_pct=100.0,
        bearish_pct=0.0,
        neutral_pct=0.0,
        agreement_score=100.0,
        conflict_pct=0.0,
        bullish_agents=["macro", "crypto"],
        bearish_agents=[],
        neutral_agents=[],
        unavailable_agents=[],
    )

    verdict = convene_committee(agent_outputs, consensus)

    assert verdict.majority_decision == "BUY"
    assert verdict.majority_pct == 100.0
    assert verdict.dissent_pct == 0.0
    assert verdict.minority_opinion is None
    assert verdict.opposing_evidence == []
    assert len(verdict.supporting_evidence) == 2
    assert "high conviction" in verdict.final_recommendation
    assert "No dissent" in verdict.reasoning


def test_split_vote_produces_minority_opinion_and_opposing_evidence():
    agent_outputs = {
        "macro": _output("macro", "bullish", 60.0, "Liquidity expanding, DXY weak."),
        "equity": _output("equity", "bearish", 55.0, "Nasdaq breadth deteriorating."),
        "news": _output("news", "bearish", 50.0, "Negative earnings sentiment dominates."),
    }
    consensus = ConsensusResult(
        bullish_pct=45.0,
        bearish_pct=55.0,
        neutral_pct=0.0,
        agreement_score=55.0,
        conflict_pct=45.0,
        bullish_agents=["macro"],
        bearish_agents=["equity", "news"],
        neutral_agents=[],
        unavailable_agents=[],
    )

    verdict = convene_committee(agent_outputs, consensus)

    assert verdict.majority_decision == "SELL"
    assert verdict.majority_pct == 55.0
    assert verdict.dissent_pct == 45.0
    assert len(verdict.supporting_evidence) == 2
    assert {e["agent"] for e in verdict.supporting_evidence} == {"equity", "news"}
    assert len(verdict.opposing_evidence) == 1
    assert verdict.opposing_evidence[0]["agent"] == "macro"
    assert verdict.minority_opinion is not None
    assert "macro" in verdict.minority_opinion
    assert "moderate conviction" in verdict.final_recommendation


def test_invalidation_risk_names_the_weakest_majority_supporter():
    agent_outputs = {
        "macro": _output("macro", "bearish", 40.0, "DXY strength is bearish for risk assets."),
        "equity": _output("equity", "bearish", 10.0, "Weak breadth, low conviction bearish read."),
        "news": _output("news", "bullish", 50.0, "Positive earnings surprises broadly."),
    }
    consensus = ConsensusResult(
        bullish_pct=45.0,
        bearish_pct=55.0,
        neutral_pct=0.0,
        agreement_score=55.0,
        conflict_pct=45.0,
        bullish_agents=["news"],
        bearish_agents=["macro", "equity"],
        neutral_agents=[],
        unavailable_agents=[],
        # macro carries most of the SELL side's weight; equity is the
        # weakest supporter and should be named as the invalidation risk.
        agent_weights={"macro": 40.0, "equity": 15.0, "news": 45.0},
    )

    verdict = convene_committee(agent_outputs, consensus)

    assert verdict.majority_decision == "SELL"
    assert verdict.invalidation_risk is not None
    assert "equity" in verdict.invalidation_risk
    assert "15.0%" in verdict.invalidation_risk


def test_low_agreement_gives_low_conviction_recommendation():
    agent_outputs = {
        "macro": _output("macro", "neutral", 40.0, "Mixed macro signals."),
        "crypto": _output("crypto", "bullish", 30.0, "Weak breakout attempt."),
        "equity": _output("equity", "bearish", 30.0, "Slight equity weakness."),
    }
    consensus = ConsensusResult(
        bullish_pct=33.3,
        bearish_pct=33.3,
        neutral_pct=33.4,
        agreement_score=33.4,
        conflict_pct=66.6,
        bullish_agents=["crypto"],
        bearish_agents=["equity"],
        neutral_agents=["macro"],
        unavailable_agents=[],
    )

    verdict = convene_committee(agent_outputs, consensus)

    assert verdict.majority_decision == "HOLD"
    assert "low conviction" in verdict.final_recommendation
    assert len(verdict.opposing_evidence) == 2


def test_unavailable_agents_noted_in_reasoning():
    agent_outputs = {
        "macro": _output("macro", "bullish", 60.0, "Bullish macro backdrop."),
    }
    consensus = ConsensusResult(
        bullish_pct=100.0,
        bearish_pct=0.0,
        neutral_pct=0.0,
        agreement_score=100.0,
        conflict_pct=0.0,
        bullish_agents=["macro"],
        bearish_agents=[],
        neutral_agents=[],
        unavailable_agents=["news", "sentiment"],
    )

    verdict = convene_committee(agent_outputs, consensus)

    assert "news" in verdict.reasoning
    assert "sentiment" in verdict.reasoning


def test_evidence_excerpt_skips_leading_markdown_header():
    summary = "*CRYPTO SUMMARY*\n\nBTC: 63,388.00 (-2.80% 24h)\n\nCrypto strength: 32/100"
    agent_outputs = {"crypto": _output("crypto", "bearish", 40.0, summary)}
    consensus = ConsensusResult(
        bullish_pct=0.0,
        bearish_pct=100.0,
        neutral_pct=0.0,
        agreement_score=100.0,
        conflict_pct=0.0,
        bullish_agents=[],
        bearish_agents=["crypto"],
        neutral_agents=[],
        unavailable_agents=[],
    )

    verdict = convene_committee(agent_outputs, consensus)

    evidence = verdict.supporting_evidence[0]["evidence"]
    assert evidence == "BTC: 63,388.00 (-2.80% 24h)"
    assert "SUMMARY" not in evidence


def test_evidence_excerpt_truncates_long_summaries():
    long_summary = "x" * 300
    agent_outputs = {"macro": _output("macro", "bullish", 60.0, long_summary)}
    consensus = ConsensusResult(
        bullish_pct=100.0,
        bearish_pct=0.0,
        neutral_pct=0.0,
        agreement_score=100.0,
        conflict_pct=0.0,
        bullish_agents=["macro"],
        bearish_agents=[],
        neutral_agents=[],
        unavailable_agents=[],
    )

    verdict = convene_committee(agent_outputs, consensus)

    assert verdict.supporting_evidence[0]["evidence"].endswith("...")
    assert len(verdict.supporting_evidence[0]["evidence"]) < 300


def test_to_dict_serializes_all_fields():
    agent_outputs = {"macro": _output("macro", "bullish", 60.0, "Bullish backdrop.")}
    consensus = ConsensusResult(
        bullish_pct=100.0,
        bearish_pct=0.0,
        neutral_pct=0.0,
        agreement_score=100.0,
        conflict_pct=0.0,
        bullish_agents=["macro"],
        bearish_agents=[],
        neutral_agents=[],
        unavailable_agents=[],
    )

    verdict = convene_committee(agent_outputs, consensus).to_dict()

    assert set(verdict) == {
        "majority_decision",
        "majority_pct",
        "dissent_pct",
        "confidence_pct",
        "supporting_evidence",
        "opposing_evidence",
        "minority_opinion",
        "final_recommendation",
        "reasoning",
        "invalidation_risk",
        "computed_at",
    }


async def test_committee_engine_convenes_from_orchestrator_output():
    orchestrator = AsyncMock()
    orchestrator.run_all.return_value = {
        "macro": _output("macro", "bullish", 60.0, "Bullish backdrop."),
        "crypto": _output("crypto", "bullish", 60.0, "Strong crypto momentum."),
    }

    verdict = await CommitteeEngine(orchestrator).convene()

    orchestrator.run_all.assert_awaited_once()
    assert verdict.majority_decision == "BUY"


async def test_committee_engine_returns_none_when_nothing_to_vote_on():
    orchestrator = AsyncMock()
    orchestrator.run_all.return_value = {"macro": _output("macro", None, None, "")}

    verdict = await CommitteeEngine(orchestrator).convene()

    assert verdict is None


async def test_committee_engine_survives_reliability_engine_failure():
    orchestrator = AsyncMock()
    orchestrator.run_all.return_value = {"macro": _output("macro", "bullish", 60.0, "Bullish.")}
    reliability_engine = AsyncMock()
    reliability_engine.evaluate_reliability.side_effect = RuntimeError("db down")

    verdict = await CommitteeEngine(orchestrator, reliability_engine).convene()

    assert verdict.majority_decision == "BUY"
