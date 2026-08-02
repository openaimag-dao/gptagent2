"""Consensus Engine -- a deterministic vote tally across the specialist
agents' direction/confidence signals (see app/services/agents/base.py).

No LLM involved: every agent's direction/confidence already comes from
data it computed itself (its own already-live-verified sub-score or item
counts, see agents/*.py), this module only aggregates those votes into a
bullish/bearish/neutral split. An agent that reported no direction this
cycle (missing underlying data) is excluded from the tally entirely --
never counted as a silent "neutral" vote, which would understate real
disagreement. If nothing reported, this returns None rather than
fabricating a 33/33/33 split from zero information.

`conflict_pct` is simply `100 - agreement_score`: the share of vote weight
that did NOT go to the dominant bucket. It is not a new measurement --
just the complement of a number already computed, made explicit so a
caller doesn't have to derive it themselves.

Optionally weighted by each agent's own historical reliability (see
app/services/reliability/engine.py's AgentReliabilityEngine): an agent
with a real track record of X% correct direction calls has its confidence
scaled by that track record, so a consistently wrong agent's vote counts
for less over time. An agent with no evaluable history yet keeps its raw
confidence -- never penalized for lacking a track record.
"""

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.services.agents.base import AgentOutput
from app.services.agents.orchestrator import AgentOrchestrator
from app.services.common.formatting import agent_evidence_excerpt
from app.services.reliability.engine import AgentReliabilityEngine

logger = logging.getLogger(__name__)

# A reporting agent always counts for at least this much weight, even at
# exactly 0 confidence -- so a unanimous-but-low-confidence set of agents
# still shows up as a real vote instead of vanishing in a division by zero.
_MIN_VOTE_WEIGHT = 1.0


@dataclass(frozen=True)
class ConsensusResult:
    bullish_pct: float
    bearish_pct: float
    neutral_pct: float
    agreement_score: float  # 0-100: the largest bucket's share of the vote
    conflict_pct: float = 0.0  # 0-100: vote weight NOT aligned with the dominant bucket
    bullish_agents: list[str] = field(default_factory=list)
    bearish_agents: list[str] = field(default_factory=list)
    neutral_agents: list[str] = field(default_factory=list)
    unavailable_agents: list[str] = field(default_factory=list)
    # {agent_name: pct of total vote weight this agent alone contributed} --
    # the same per-agent weight compute_consensus() already calculates while
    # building the bucket totals below, kept instead of discarded so
    # "which engine has the strongest influence" (v8.0) is real reuse of an
    # already-computed number, not a new calculation.
    agent_weights: dict[str, float] = field(default_factory=dict)
    # {agent_name: first substantive line of that agent's own summary} --
    # the same evidence-excerpt CommitteeEngine already quotes (shared via
    # agent_evidence_excerpt()), attached here too so "why agents agree/
    # disagree" (v8.0) can quote each agent's real reasoning instead of
    # just naming which bucket it landed in.
    agent_evidence: dict[str, str] = field(default_factory=dict)
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def strongest_agent(self) -> str | None:
        if not self.agent_weights:
            return None
        return max(self.agent_weights, key=self.agent_weights.get)

    @property
    def invalidation_risk(self) -> str | None:
        """v9.0 "What could invalidate this view" -- names the dominant
        bucket's weakest-weight agent and what agreement would fall to if
        it reversed. Same derivation CommitteeVerdict.invalidation_risk
        already uses (the weakest supporter of a majority), applied here
        directly to Consensus's own buckets so /consensus can answer this
        without a Committee convene()."""
        buckets = {
            "bullish": (self.bullish_pct, self.bullish_agents),
            "bearish": (self.bearish_pct, self.bearish_agents),
            "neutral": (self.neutral_pct, self.neutral_agents),
        }
        dominant_direction, (_, dominant_agents) = max(buckets.items(), key=lambda kv: kv[1][0])
        weakest = min(
            (a for a in dominant_agents if a in self.agent_weights),
            key=lambda a: self.agent_weights[a],
            default=None,
        )
        if weakest is None:
            return None
        weight = self.agent_weights[weakest]
        return (
            f"{weakest} contributes the least weight to the {dominant_direction} lean "
            f"({weight}%) -- if it reverses, agreement would fall toward "
            f"{round(self.agreement_score - weight, 1)}%."
        )

    def to_dict(self) -> dict:
        return {
            "bullish_pct": self.bullish_pct,
            "bearish_pct": self.bearish_pct,
            "neutral_pct": self.neutral_pct,
            "agreement_score": self.agreement_score,
            "conflict_pct": self.conflict_pct,
            "bullish_agents": self.bullish_agents,
            "bearish_agents": self.bearish_agents,
            "neutral_agents": self.neutral_agents,
            "unavailable_agents": self.unavailable_agents,
            "agent_weights": self.agent_weights,
            "agent_evidence": self.agent_evidence,
            "strongest_agent": self.strongest_agent,
            "invalidation_risk": self.invalidation_risk,
            "computed_at": self.computed_at.isoformat(),
        }


def compute_consensus(
    agent_outputs: dict[str, AgentOutput], reliability: dict[str, float] | None = None
) -> ConsensusResult | None:
    """Pure function: {agent_name: AgentOutput} -> ConsensusResult.

    Each reporting agent's confidence (floored at _MIN_VOTE_WEIGHT) is its
    weight toward its own direction bucket; buckets are normalized to
    percentages of the total weight actually cast. When `reliability`
    (an optional {agent_name: accuracy_pct} map from AgentReliabilityEngine)
    includes an agent, that agent's weight is additionally scaled by its
    own historical accuracy -- an agent absent from `reliability` (no
    evaluable track record yet) keeps its raw confidence-only weight.
    """
    weights = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
    bullish_agents: list[str] = []
    bearish_agents: list[str] = []
    neutral_agents: list[str] = []
    unavailable_agents: list[str] = []
    agents_by_direction = {
        "bullish": bullish_agents,
        "bearish": bearish_agents,
        "neutral": neutral_agents,
    }
    per_agent_weight: dict[str, float] = {}

    for name, output in agent_outputs.items():
        if output.direction is None:
            unavailable_agents.append(name)
            continue
        weight = (
            max(output.confidence, _MIN_VOTE_WEIGHT)
            if output.confidence is not None
            else _MIN_VOTE_WEIGHT
        )
        if reliability is not None and name in reliability:
            weight *= reliability[name] / 100.0
        weights[output.direction] += weight
        agents_by_direction[output.direction].append(name)
        per_agent_weight[name] = weight

    total_weight = sum(weights.values())
    if total_weight == 0:
        return None

    percentages = {name: 100.0 * weight / total_weight for name, weight in weights.items()}
    rounded = {name: round(pct, 1) for name, pct in percentages.items()}
    drift = round(100.0 - sum(rounded.values()), 1)
    if drift != 0:
        largest = max(percentages, key=percentages.get)
        rounded[largest] = round(rounded[largest] + drift, 1)

    agreement_score = max(rounded.values())
    agent_weights = {
        name: round(100.0 * weight / total_weight, 1) for name, weight in per_agent_weight.items()
    }
    agent_evidence = {
        name: agent_evidence_excerpt(agent_outputs[name].summary) for name in per_agent_weight
    }
    return ConsensusResult(
        bullish_pct=rounded["bullish"],
        bearish_pct=rounded["bearish"],
        neutral_pct=rounded["neutral"],
        agreement_score=agreement_score,
        conflict_pct=round(100.0 - agreement_score, 1),
        bullish_agents=bullish_agents,
        bearish_agents=bearish_agents,
        neutral_agents=neutral_agents,
        unavailable_agents=unavailable_agents,
        agent_weights=agent_weights,
        agent_evidence=agent_evidence,
    )


def consensus_evolution(earlier: dict | None, later: dict | None) -> dict | None:
    """Pure function: two ConsensusResult.to_dict()-shaped dicts (e.g. the
    latest live tally and the consensus column of the most recent
    MarketSnapshot Replay already persisted) -> what changed between them.
    v9.0's "Consensus should explain ... confidence evolution." Returns
    None when either side is missing rather than guessing a trend.
    """
    if earlier is None or later is None:
        return None
    earlier_agreement = earlier.get("agreement_score")
    later_agreement = later.get("agreement_score")
    if earlier_agreement is None or later_agreement is None:
        return None

    agreement_delta = round(later_agreement - earlier_agreement, 1)
    bullish_delta = round(later.get("bullish_pct", 0.0) - earlier.get("bullish_pct", 0.0), 1)
    bearish_delta = round(later.get("bearish_pct", 0.0) - earlier.get("bearish_pct", 0.0), 1)
    strongest_from = earlier.get("strongest_agent")
    strongest_to = later.get("strongest_agent")
    strongest_changed = strongest_from != strongest_to

    if agreement_delta > 0:
        trend = f"Consensus agreement rose {agreement_delta:+.1f}pts"
    elif agreement_delta < 0:
        trend = f"Consensus agreement fell {agreement_delta:+.1f}pts"
    else:
        trend = "Consensus agreement is unchanged"
    summary = f"{trend} (from {earlier_agreement}% to {later_agreement}%)."
    if strongest_changed and strongest_from is not None and strongest_to is not None:
        summary += f" Strongest influence shifted from {strongest_from} to {strongest_to}."
    elif strongest_to is not None:
        summary += f" {strongest_to} remains the strongest influence."

    return {
        "agreement_score_delta": agreement_delta,
        "bullish_pct_delta": bullish_delta,
        "bearish_pct_delta": bearish_delta,
        "strongest_agent_from": strongest_from,
        "strongest_agent_to": strongest_to,
        "strongest_agent_changed": strongest_changed,
        "summary": summary,
    }


class ConsensusEngine:
    """Runs every specialist agent and tallies their votes -- the thin
    orchestration wrapper around compute_consensus(), same shape as
    ScenarioEngine/ConvictionEngine wrapping their own pure functions."""

    def __init__(
        self,
        agent_orchestrator: AgentOrchestrator,
        reliability_engine: AgentReliabilityEngine | None = None,
    ) -> None:
        self._agent_orchestrator = agent_orchestrator
        self._reliability_engine = reliability_engine

    async def compute(self) -> ConsensusResult | None:
        agent_outputs = await self._agent_orchestrator.run_all()

        reliability: dict[str, float] | None = None
        if self._reliability_engine is not None:
            try:
                reliability = await self._reliability_engine.evaluate_reliability()
                await self._reliability_engine.log(agent_outputs)
            except Exception:
                logger.warning(
                    "Agent reliability tracking failed; continuing without it", exc_info=True
                )
                reliability = None

        return compute_consensus(agent_outputs, reliability)
