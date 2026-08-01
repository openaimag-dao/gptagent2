"""Technical Agent -- v5.3 TradingView MCP Integration. Wraps
TechnicalAnalysisEngine's combined multi-timeframe AI Technical Score for
BTC (the platform's macro-proxy symbol every other deterministic engine
already speaks to -- same convention as AgentReliabilityEngine) into an
AgentOutput, so Consensus/Committee/Replay/the Critical Alert System all
pick it up for free the same way they already do for the other 5 agents --
"feed signals into Committee, Consensus, ... Replay" from the mission,
with zero changes to any of those engines (see
app.services.agents.orchestrator's downstream-consumer-agnostic dict)."""

from app.services.agents.base import AgentOutput
from app.services.common.scoring import direction_from_score
from app.services.technical.engine import TechnicalAnalysisEngine

PROXY_SYMBOL = "BTC"


class TechnicalAgent:
    def __init__(self, technical_engine: TechnicalAnalysisEngine) -> None:
        self._technical_engine = technical_engine

    async def summarize(self) -> AgentOutput:
        result = await self._technical_engine.analyze(PROXY_SYMBOL)

        if result is None:
            return AgentOutput(
                agent="technical",
                summary=(
                    f"*TECHNICAL SUMMARY*\n\nNo technical analysis available yet for "
                    f"{PROXY_SYMBOL}."
                ),
                data={"available": False},
            )

        score = None
        if result["bullish_score"] is not None and result["bearish_score"] is not None:
            score = 50.0 + (result["bullish_score"] - result["bearish_score"]) / 2.0
        direction, confidence = direction_from_score(score)

        lines = [
            "*TECHNICAL SUMMARY*",
            "",
            f"{PROXY_SYMBOL} bullish {result['bullish_score']} / bearish {result['bearish_score']}",
            f"Trend strength: {result['trend_strength']} | Confidence: {result['confidence']}%",
        ]
        if result["active_signals"]:
            lines.append("Active signals: " + ", ".join(result["active_signals"]))
        alignment = result["high_confidence_alignment"]
        if alignment is not None:
            lines.append(f"{alignment['signal']}: " + "; ".join(alignment["reasons"]))

        return AgentOutput(
            agent="technical",
            summary="\n".join(lines),
            data={"available": True, **result},
            direction=direction,
            confidence=confidence,
        )
