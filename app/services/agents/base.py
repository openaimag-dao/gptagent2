from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class AgentOutput:
    """The uniform shape every agent returns, so the Reasoning Agent and
    /api/agents can treat all five the same way regardless of what each one
    actually looked at.

    `direction`/`confidence` are optional and default to None: each agent
    computes them from data it already has (never fabricated), and reports
    None rather than a guessed "neutral" when that data isn't available this
    cycle. Added after `agent`/`summary`/`data`/`generated_at` so every
    existing construction call keeps working unchanged -- see
    ConsensusEngine (app/services/consensus/engine.py) for the first
    consumer of these two fields.
    """

    agent: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    direction: str | None = None  # "bullish" | "bearish" | "neutral" | None
    confidence: float | None = None  # 0-100, or None alongside direction=None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "summary": self.summary,
            "data": self.data,
            "generated_at": self.generated_at.isoformat(),
            "direction": self.direction,
            "confidence": self.confidence,
        }
