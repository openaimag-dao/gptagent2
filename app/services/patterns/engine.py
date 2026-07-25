import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import PatternSignal
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.patterns.detectors import (
    detect_bearish_engulfing,
    detect_bullish_engulfing,
    detect_death_cross,
    detect_doji,
    detect_golden_cross,
    detect_hammer,
)

logger = logging.getLogger(__name__)

# (pattern name, direction) -> detector -- keeps compute_and_store a simple loop
# rather than one branch per pattern.
_BULLISH = "bullish"
_BEARISH = "bearish"
_NEUTRAL = "neutral"


class PatternEngine:
    """Scans a symbol's full stored history for well-known technical patterns."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def compute_and_store(
        self, symbol: str, model: type, timeframe: Timeframe = Timeframe.DAILY
    ) -> int:
        rows = await get_series(self._session_factory, model, symbol, timeframe)
        if len(rows) < 2:
            return 0

        opens = [float(r.open) for r in rows]
        highs = [float(r.high) for r in rows]
        lows = [float(r.low) for r in rows]
        closes = [float(r.close) for r in rows]
        sma_50 = [float(r.sma_50) if r.sma_50 is not None else None for r in rows]
        sma_200 = [float(r.sma_200) if r.sma_200 is not None else None for r in rows]

        detections: list[tuple[str, str, list[bool]]] = [
            ("doji", _NEUTRAL, detect_doji(opens, highs, lows, closes)),
            ("hammer", _BULLISH, detect_hammer(opens, highs, lows, closes)),
            ("bullish_engulfing", _BULLISH, detect_bullish_engulfing(opens, closes)),
            ("bearish_engulfing", _BEARISH, detect_bearish_engulfing(opens, closes)),
            ("golden_cross", _BULLISH, detect_golden_cross(sma_50, sma_200)),
            ("death_cross", _BEARISH, detect_death_cross(sma_50, sma_200)),
        ]

        signal_rows = [
            {
                "symbol": symbol,
                "timeframe": timeframe.value,
                "timestamp": rows[i].timestamp,
                "pattern_name": name,
                "direction": direction,
            }
            for name, direction, flags in detections
            for i, hit in enumerate(flags)
            if hit
        ]
        if not signal_rows:
            return 0

        async with self._session_factory() as session:
            stmt = pg_insert(PatternSignal).values(signal_rows)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["symbol", "timeframe", "timestamp", "pattern_name"]
            )
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount or 0

    async def get_latest(
        self, symbol: str, timeframe: Timeframe = Timeframe.DAILY, limit: int = 10
    ) -> list[PatternSignal]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(PatternSignal)
                .where(PatternSignal.symbol == symbol, PatternSignal.timeframe == timeframe.value)
                .order_by(PatternSignal.timestamp.desc())
                .limit(limit)
            )
            return list(rows)
