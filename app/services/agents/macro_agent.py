"""Macro Agent -- Federal Reserve / rates / inflation / liquidity / bond
market / dollar / yield curve. Reuses live macro AssetPrice rows, the
regime detector's inputs and the Global Market Score's liquidity/macro
sub-scores; computes nothing new, only summarizes.

The requested inputs list also includes ECB, BOJ and PBOC policy and
CPI/PPI/money-supply series. This project only collects US-centric macro
data (Fed Funds Rate via FRED, CPI/M2 via the Historical Intelligence
Engine where synced) -- non-US central bank rates and PPI have no
configured source, so this agent reports on what it actually has rather
than fabricating a global central-bank picture.
"""

from app.services.agents.base import AgentOutput
from app.services.common.formatting import asset_change_dict, format_asset_lines
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository

MACRO_SYMBOLS: tuple[str, ...] = (
    "DXY",
    "GOLD",
    "SILVER",
    "OIL",
    "VIX",
    "US10Y",
    "US30Y",
    "FEDRATE",
)


class MacroAgent:
    def __init__(
        self,
        market_repository: MarketRepository,
        global_score_engine: GlobalScoreEngine,
    ) -> None:
        self._market_repository = market_repository
        self._global_score_engine = global_score_engine

    async def summarize(self) -> AgentOutput:
        assets = await self._market_repository.get_latest()
        global_score = await self._global_score_engine.get_latest()

        lines = ["*MACRO SUMMARY*", ""]
        lines.extend(format_asset_lines(assets, MACRO_SYMBOLS))

        direction: str | None = None
        confidence: float | None = None
        if global_score is not None:
            lines.append("")
            lines.append(
                f"Liquidity: {global_score.liquidity_score}/100 | "
                f"Macro pressure: {global_score.macro_pressure_score}/100"
            )
            liquidity_analysis = (
                f"Liquidity score {global_score.liquidity_score}/100 "
                f"(derived from Fed Funds Rate direction)."
            )
            risk_assessment = (
                f"Macro pressure {global_score.macro_pressure_score}/100 "
                f"(derived from DXY + US10Y moves); Fear {global_score.fear_score}/100."
            )
            # Risk-on/risk-off are already the Global Score's own read of
            # macro conditions for risk assets -- reused here rather than
            # deriving a second, competing directional signal.
            diff = global_score.risk_on_score - global_score.risk_off_score
            direction = "bullish" if diff > 0 else "bearish" if diff < 0 else "neutral"
            confidence = min(abs(diff), 100.0)
        else:
            liquidity_analysis = "Not yet computed -- run /score or GET /api/global-score first."
            risk_assessment = "Not yet computed."

        return AgentOutput(
            agent="macro",
            summary="\n".join(lines),
            data={
                "assets": asset_change_dict(assets, MACRO_SYMBOLS),
                "liquidity_analysis": liquidity_analysis,
                "risk_assessment": risk_assessment,
                "note": (
                    "Covers US Fed/DXY/rates/VIX/Gold/Silver/Oil only -- ECB/BOJ/PBOC "
                    "policy and CPI/PPI/M2 have no configured live-quote source in "
                    "this project (CPI/M2 are available historically via the "
                    "Historical Intelligence Engine where synced, see /api/history)."
                ),
            },
            direction=direction,
            confidence=confidence,
        )
