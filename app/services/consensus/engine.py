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
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.services.agents.base import AgentOutput
from app.services.agents.orchestrator import AgentOrchestrator

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
    computed_at: datetime = field(default_factory=lambda: datetime.now(UTC))

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
            "computed_at": self.computed_at.isoformat(),
        }


def compute_consensus(agent_outputs: dict[str, AgentOutput]) -> ConsensusResult | None:
    """Pure function: {agent_name: AgentOutput} -> ConsensusResult.

    Each reporting agent's confidence (floored at _MIN_VOTE_WEIGHT) is its
    weight toward its own direction bucket; buckets are normalized to
    percentages of the total weight actually cast.
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

    for name, output in agent_outputs.items():
        if output.direction is None:
            unavailable_agents.append(name)
            continue
        weight = (
            max(output.confidence, _MIN_VOTE_WEIGHT)
            if output.confidence is not None
            else _MIN_VOTE_WEIGHT
        )
        weights[output.direction] += weight
        agents_by_direction[output.direction].append(name)

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
    )


class ConsensusEngine:
    """Runs every specialist agent and tallies their votes -- the thin
    orchestration wrapper around compute_consensus(), same shape as
    ScenarioEngine/ConvictionEngine wrapping their own pure functions."""

    def __init__(self, agent_orchestrator: AgentOrchestrator) -> None:
        self._agent_orchestrator = agent_orchestrator

    async def compute(self) -> ConsensusResult | None:
        agent_outputs = await self._agent_orchestrator.run_all()
        return compute_consensus(agent_outputs)
