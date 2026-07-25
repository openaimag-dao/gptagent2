from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class AgentOutput:
    """The uniform shape every agent returns, so the Reasoning Agent and
    /api/agents can treat all five the same way regardless of what each one
    actually looked at."""

    agent: str
    summary: str
    data: dict[str, Any] = field(default_factory=dict)
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "summary": self.summary,
            "data": self.data,
            "generated_at": self.generated_at.isoformat(),
        }
