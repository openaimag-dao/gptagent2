"""AI Investment Committee -- v4.0 Phase 4.

Every agent's vote already exists (AgentOrchestrator.run_all()) and the
weighted bullish/bearish/neutral percentages already exist
(compute_consensus()); this engine adds the structured layer the raw
percentages don't provide: a single named majority decision, the
minority's dissenting evidence, an explicit dissent %, and one final
recommendation with reasoning -- all derived deterministically from the
same agent votes already tallied by ConsensusEngine, never fabricated or
guessed. No LLM involved, consistent with every other deterministic
engine in this project (Consensus/Scenario/Conviction/Global Score).

Like Consensus itself, a committee verdict is computed on demand rather
than persisted -- there is nothing here that isn't already derivable from
data another engine already computed.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.services.agents.base import AgentOutput
from app.services.agents.orchestrator import AgentOrchestrator
from app.services.common.formatting import agent_evidence_excerpt
from app.services.consensus.engine import ConsensusResult, compute_consensus
from app.services.reliability.engine import AgentReliabilityEngine

_DECISION_BY_DIRECTION: dict[str, str] = {"bullish": "BUY", "bearish": "SELL", "neutral": "HOLD"}


@dataclass(frozen=True)
class CommitteeVerdict:
    majority_decision: str
    majority_pct: float
    dissent_pct: float
    confidence_pct: float
    supporting_evidence: list[dict] = field(default_factory=list)
    opposing_evidence: list[dict] = field(default_factory=list)
    minority_opinion: str | None = None
    final_recommendation: str = ""
    reasoning: str = ""
    # v8.0 "what could invalidate it" -- deterministic, reused from the same
    # per-agent weights ConsensusResult.agent_weights already computes:
    # names the majority's weakest supporter and what dissent would rise to
    # if it flipped, rather than inventing a new signal.
    invalidation_risk: str | None = None
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict:
        return {
            "majority_decision": self.majority_decision,
            "majority_pct": self.majority_pct,
            "dissent_pct": self.dissent_pct,
            "confidence_pct": self.confidence_pct,
            "supporting_evidence": self.supporting_evidence,
            "opposing_evidence": self.opposing_evidence,
            "minority_opinion": self.minority_opinion,
            "final_recommendation": self.final_recommendation,
            "reasoning": self.reasoning,
            "invalidation_risk": self.invalidation_risk,
            "computed_at": self.computed_at.isoformat(),
        }


def convene_committee(
    agent_outputs: dict[str, AgentOutput], consensus: ConsensusResult
) -> CommitteeVerdict:
    """Pure function: agent votes + an already-computed ConsensusResult ->
    a structured committee verdict. Does not re-derive the vote
    percentages -- those are compute_consensus()'s job."""
    pct_by_direction = {
        "bullish": consensus.bullish_pct,
        "bearish": consensus.bearish_pct,
        "neutral": consensus.neutral_pct,
    }
    majority_direction = max(pct_by_direction, key=pct_by_direction.get)
    majority_pct = pct_by_direction[majority_direction]
    dissent_pct = round(100.0 - majority_pct, 1)
    majority_decision = _DECISION_BY_DIRECTION[majority_direction]

    agents_by_direction = {
        "bullish": consensus.bullish_agents,
        "bearish": consensus.bearish_agents,
        "neutral": consensus.neutral_agents,
    }
    supporting_names = agents_by_direction[majority_direction]
    opposing_names_by_direction = {
        name: direction
        for direction in ("bullish", "bearish", "neutral")
        if direction != majority_direction
        for name in agents_by_direction[direction]
    }

    supporting_evidence = [
        {
            "agent": name,
            "direction": majority_direction,
            "confidence": agent_outputs[name].confidence,
            "evidence": agent_evidence_excerpt(agent_outputs[name].summary),
        }
        for name in supporting_names
        if name in agent_outputs
    ]
    opposing_evidence = [
        {
            "agent": name,
            "direction": direction,
            "confidence": agent_outputs[name].confidence,
            "evidence": agent_evidence_excerpt(agent_outputs[name].summary),
        }
        for name, direction in opposing_names_by_direction.items()
        if name in agent_outputs
    ]

    minority_opinion = None
    if opposing_evidence:
        clauses = [f"{e['agent']} ({e['direction']}): {e['evidence']}" for e in opposing_evidence]
        minority_opinion = "; ".join(clauses)

    confidence_pct = round(consensus.agreement_score, 1)
    if confidence_pct >= 70:
        conviction = "high conviction"
    elif confidence_pct >= 50:
        conviction = "moderate conviction"
    else:
        conviction = "low conviction"
    final_recommendation = f"{majority_decision} ({conviction})"

    reasoning_parts = [
        f"Majority decision: {majority_decision} with {majority_pct}% of weighted committee "
        f"votes ({', '.join(sorted(supporting_names)) or 'no agent'})."
    ]
    if opposing_evidence:
        reasoning_parts.append(
            f"Dissent: {dissent_pct}% of the vote opposes, from "
            f"{', '.join(sorted(opposing_names_by_direction)) or 'no agent'}."
        )
    else:
        reasoning_parts.append("No dissent -- every reporting agent agrees.")
    if consensus.unavailable_agents:
        reasoning_parts.append(f"No vote from: {', '.join(consensus.unavailable_agents)}.")
    reasoning = " ".join(reasoning_parts)

    invalidation_risk = None
    weights = consensus.agent_weights
    weakest_supporter = min(
        (n for n in supporting_names if n in weights), key=lambda n: weights[n], default=None
    )
    if weakest_supporter is not None:
        invalidation_risk = (
            f"{weakest_supporter} contributes the least weight to the {majority_decision} "
            f"majority ({weights[weakest_supporter]}%) -- if it reverses, dissent would rise "
            f"toward {round(dissent_pct + weights[weakest_supporter], 1)}%."
        )
    elif opposing_evidence:
        invalidation_risk = (
            f"{dissent_pct}% already opposes "
            f"({', '.join(sorted(opposing_names_by_direction))}); no majority-side vote weight "
            "data is available to gauge how close a flip would be."
        )

    return CommitteeVerdict(
        majority_decision=majority_decision,
        majority_pct=majority_pct,
        dissent_pct=dissent_pct,
        confidence_pct=confidence_pct,
        supporting_evidence=supporting_evidence,
        opposing_evidence=opposing_evidence,
        minority_opinion=minority_opinion,
        final_recommendation=final_recommendation,
        reasoning=reasoning,
        invalidation_risk=invalidation_risk,
    )


class CommitteeEngine:
    """Convenes the committee -- runs every agent, tallies the vote, and
    layers the majority/minority/evidence/recommendation structure on top.
    Same thin-wrapper shape as ConsensusEngine/ScenarioEngine around their
    own pure functions."""

    def __init__(
        self,
        agent_orchestrator: AgentOrchestrator,
        reliability_engine: AgentReliabilityEngine | None = None,
    ) -> None:
        self._agent_orchestrator = agent_orchestrator
        self._reliability_engine = reliability_engine

    async def _safe_reliability(self) -> dict[str, float] | None:
        if self._reliability_engine is None:
            return None
        try:
            return await self._reliability_engine.evaluate_reliability()
        except Exception:
            return None

    async def convene(self) -> CommitteeVerdict | None:
        # run_all() and evaluate_reliability() read different tables and
        # neither depends on the other's result -- gathered rather than
        # sequential.
        agent_outputs, reliability = await asyncio.gather(
            self._agent_orchestrator.run_all(),
            self._safe_reliability(),
        )

        consensus = compute_consensus(agent_outputs, reliability)
        if consensus is None:
            return None
        return convene_committee(agent_outputs, consensus)
