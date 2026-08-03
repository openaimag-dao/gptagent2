"""Risk Agent -- votes off GlobalScoreEngine's own `risk_score` (0-100,
already a weighted blend of risk_off/fear/macro_pressure -- see
app/services/global_score/engine.py), a genuinely different composition
than MacroAgent's own risk_on-vs-risk_off diff despite sharing some inputs.
Higher risk is bearish for risk assets, so this reuses the same
`direction_from_score` primitive every other centered-at-50 score in this
project uses, just inverted (100 - risk_score) rather than deriving a new
threshold scheme.
"""

from app.services.agents.base import AgentOutput
from app.services.common.scoring import direction_from_score
from app.services.global_score.engine import GlobalScoreEngine


class RiskAgent:
    def __init__(self, global_score_engine: GlobalScoreEngine) -> None:
        self._global_score_engine = global_score_engine

    async def summarize(self) -> AgentOutput:
        global_score = await self._global_score_engine.get_latest()

        if global_score is None or global_score.risk_score is None:
            lines = [
                "*RISK SUMMARY*",
                "",
                "Not yet computed -- run /score or GET /api/global-score first.",
            ]
            return AgentOutput(agent="risk", summary="\n".join(lines), data={"available": False})

        direction, confidence = direction_from_score(100.0 - global_score.risk_score)

        lines = [
            "*RISK SUMMARY*",
            "",
            f"Risk score: {global_score.risk_score}/100 "
            f"(risk-off {global_score.risk_off_score}/100, fear {global_score.fear_score}/100, "
            f"macro pressure {global_score.macro_pressure_score}/100)",
        ]

        return AgentOutput(
            agent="risk",
            summary="\n".join(lines),
            data={"available": True, "risk_score": global_score.risk_score},
            direction=direction,
            confidence=confidence,
        )
