"""Whale Agent -- votes off WhaleIntelligenceEngine's own real derivatives
classification (long_heavy/short_heavy/balanced, derived from funding rate
and long/short ratio, see app/services/whales/engine.py). Reports no
direction when CoinGlass/CoinGecko derivatives data isn't available this
cycle -- never a fabricated vote.
"""

from app.services.agents.base import AgentOutput
from app.services.whales.engine import WhaleIntelligenceEngine

PROXY_SYMBOL = "BTC"

_CLASSIFICATION_TO_DIRECTION: dict[str, str] = {
    "long_heavy": "bullish",
    "short_heavy": "bearish",
    "balanced": "neutral",
}


def _confidence(snapshot: dict) -> float | None:
    """0-100 confidence from how far real positioning sits from balanced --
    the same ratio/funding-distance proxy already used to derive this
    engine's own classification thresholds (app/services/whales/engine.py's
    _RATIO_HIGH/_classify), not a second measurement."""
    ratio = snapshot.get("long_short_ratio")
    funding = snapshot.get("funding_rate")
    if ratio is not None:
        return min(100.0, abs(ratio - 1.0) / 0.5 * 100)
    if funding is not None:
        return min(100.0, abs(funding) / 0.0005 * 100)
    return None


class WhaleAgent:
    def __init__(self, whale_engine: WhaleIntelligenceEngine) -> None:
        self._whale_engine = whale_engine

    async def summarize(self) -> AgentOutput:
        snapshot = await self._whale_engine.get_snapshot(PROXY_SYMBOL)

        if not snapshot.get("available"):
            lines = [
                "*WHALE SUMMARY*",
                "",
                f"Derivatives data unavailable: {snapshot.get('reason', 'no data')}",
            ]
            return AgentOutput(
                agent="whale",
                summary="\n".join(lines),
                data={"available": False, "reason": snapshot.get("reason")},
            )

        classification = snapshot.get("classification")
        direction = _CLASSIFICATION_TO_DIRECTION.get(classification)
        confidence = _confidence(snapshot) if direction is not None else None

        lines = [
            "*WHALE SUMMARY*",
            "",
            f"Classification: {classification or 'unknown'}",
            f"Long/short ratio: {snapshot.get('long_short_ratio')}",
            f"Funding rate: {snapshot.get('funding_rate')}",
        ]

        return AgentOutput(
            agent="whale",
            summary="\n".join(lines),
            data={"available": True, **snapshot},
            direction=direction,
            confidence=confidence,
        )
