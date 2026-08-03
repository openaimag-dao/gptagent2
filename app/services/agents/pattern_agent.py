"""Pattern Agent -- votes off the last N real detected candlestick/moving-
average patterns from PatternEngine (app/services/patterns/engine.py).
`PatternSignal` has no confidence field of its own, so confidence here is a
genuine, non-fabricated derivation: recency-weighted agreement across the
actually-detected patterns (a more recent pattern counts for more than an
older one) -- not an invented number, a real measurement of how much the
recent pattern history agrees with itself.
"""

from app.database.models import PatternSignal
from app.services.agents.base import AgentOutput
from app.services.history.schemas import Timeframe
from app.services.patterns.engine import PatternEngine

PROXY_SYMBOL = "BTC"
_LOOKBACK = 10


def _recency_weighted_direction(signals: list[PatternSignal]) -> tuple[str | None, float | None]:
    """Pure function: signals ordered most-recent-first -> (direction,
    confidence), where each signal's vote weight is 1/(rank+1) so a more
    recent pattern counts for more. Confidence is the dominant direction's
    share of total weight -- real agreement, not a guessed number. None when
    no patterns have been detected at all."""
    if not signals:
        return None, None
    weights = {"bullish": 0.0, "bearish": 0.0, "neutral": 0.0}
    for rank, signal in enumerate(signals):
        weights[signal.direction] += 1.0 / (rank + 1)
    total = sum(weights.values())
    if total == 0:
        return None, None
    dominant = max(weights, key=weights.get)
    confidence = round(100.0 * weights[dominant] / total, 1)
    return dominant, confidence


class PatternAgent:
    def __init__(self, pattern_engine: PatternEngine) -> None:
        self._pattern_engine = pattern_engine

    async def summarize(self) -> AgentOutput:
        from app.services.history.registry import find_symbol_config

        config = find_symbol_config(PROXY_SYMBOL)
        signals = (
            await self._pattern_engine.get_latest(
                config.symbol, timeframe=Timeframe.DAILY, limit=_LOOKBACK
            )
            if config is not None
            else []
        )

        direction, confidence = _recency_weighted_direction(signals)

        if not signals:
            lines = ["*PATTERN SUMMARY*", "", "No patterns detected in recent history."]
            return AgentOutput(
                agent="pattern",
                summary="\n".join(lines),
                data={"available": False, "patterns": []},
            )

        lines = ["*PATTERN SUMMARY*", ""]
        lines.extend(
            f"{s.pattern_name} ({s.direction}) at {s.timestamp.date()}" for s in signals[:5]
        )

        return AgentOutput(
            agent="pattern",
            summary="\n".join(lines),
            data={
                "available": True,
                "patterns": [
                    {
                        "pattern_name": s.pattern_name,
                        "direction": s.direction,
                        "timestamp": s.timestamp.isoformat(),
                    }
                    for s in signals
                ],
            },
            direction=direction,
            confidence=confidence,
        )
