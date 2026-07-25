import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.history.registry import HistorySymbolConfig
from app.services.history.repository import upsert_candles
from app.services.history.schemas import Timeframe
from app.services.history.validation import Gap

logger = logging.getLogger(__name__)


async def repair_duplicates(
    session_factory: async_sessionmaker[AsyncSession],
    model: type,
    symbol: str,
    timeframe: Timeframe,
) -> int:
    """Deletes duplicate (symbol, timeframe, timestamp) rows, keeping the lowest id.

    The unique constraint on the table prevents this engine from ever writing
    a fresh duplicate, so this is a safety net for anomalies in pre-existing
    or externally-imported data rather than something normal syncs trigger.
    """
    async with session_factory() as session:
        rows = list(
            await session.scalars(
                select(model)
                .where(model.symbol == symbol, model.timeframe == timeframe.value)
                .order_by(model.timestamp.asc(), model.id.asc())
            )
        )

        seen: set = set()
        to_delete: list[int] = []
        for row in rows:
            if row.timestamp in seen:
                to_delete.append(row.id)
            else:
                seen.add(row.timestamp)

        if not to_delete:
            return 0

        await session.execute(delete(model).where(model.id.in_(to_delete)))
        await session.commit()
        return len(to_delete)


async def repair_gaps(
    session_factory: async_sessionmaker[AsyncSession],
    config: HistorySymbolConfig,
    timeframe: Timeframe,
    gaps: list[Gap],
) -> int:
    """Re-fetches candles for each detected gap window and inserts whatever the
    provider actually returns -- if a gap reflects a real market closure
    (weekend, holiday) rather than missing data, nothing gets inserted."""
    total_inserted = 0
    for gap in gaps:
        candles = await config.provider.fetch_candles(config.symbol, timeframe, gap.after)
        candles = [c for c in candles if gap.after < c.timestamp < gap.before]
        total_inserted += await upsert_candles(session_factory, config.model, candles)
    return total_inserted
