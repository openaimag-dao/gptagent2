"""Equity Agent -- NASDAQ/SPX/DJI/RUT and the Magnificent 7.

Sector rotation, market breadth (advance/decline) and volume-profile
analysis are explicitly out of scope: this project collects index- and
single-name-level price data only, no sector classification or exchange
breadth feed, so those two outputs are reported as honestly unavailable
rather than inferred from index moves alone.
"""

from app.services.agents.base import AgentOutput
from app.services.common.formatting import asset_change_dict, format_asset_lines
from app.services.common.scoring import direction_from_score
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository

INDEX_SYMBOLS: tuple[str, ...] = ("NASDAQ", "SPX", "DJI", "RUT")
MAG7_SYMBOLS: tuple[str, ...] = ("AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL")

_SECTOR_UNAVAILABLE_REASON = (
    "No sector-classification or market-breadth (advance/decline) data source "
    "is configured in this project -- only index- and single-name-level prices "
    "are collected, so sector rotation and breadth are reported as unavailable "
    "rather than inferred from index moves alone."
)


class EquityAgent:
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

        lines = ["*EQUITY SUMMARY*", ""]
        lines.append("Indices:")
        lines.extend(format_asset_lines(assets, INDEX_SYMBOLS))
        lines.append("Magnificent 7:")
        lines.extend(format_asset_lines(assets, MAG7_SYMBOLS))

        by_symbol = {a.symbol: a for a in assets}
        mag7_changes = [
            float(by_symbol[s].change_pct_24h)
            for s in MAG7_SYMBOLS
            if s in by_symbol and by_symbol[s].change_pct_24h is not None
        ]
        sector_leadership = (
            f"Magnificent 7 average 24h change: {sum(mag7_changes) / len(mag7_changes):+.2f}% "
            f"({len(mag7_changes)}/{len(MAG7_SYMBOLS)} names available) -- single-name "
            "leadership only, not a real sector breakdown."
            if mag7_changes
            else "Magnificent 7 data not available yet."
        )

        risk_appetite = (
            f"Stock strength: {global_score.stock_strength_score}/100"
            if global_score is not None
            else "Not yet computed -- run /score or GET /api/global-score first."
        )

        direction, confidence = direction_from_score(
            global_score.stock_strength_score if global_score is not None else None
        )

        return AgentOutput(
            agent="equity",
            summary="\n".join(lines),
            data={
                "indices": asset_change_dict(assets, INDEX_SYMBOLS),
                "magnificent_seven": asset_change_dict(assets, MAG7_SYMBOLS),
                "risk_appetite": risk_appetite,
                "sector_leadership": sector_leadership,
                "sector_rotation": None,
                "market_breadth": None,
                "unavailable_reason": _SECTOR_UNAVAILABLE_REASON,
            },
            direction=direction,
            confidence=confidence,
        )
