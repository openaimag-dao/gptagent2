import logging
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.history.indicators import (
    compute_atr,
    compute_macd,
    compute_moving_averages,
    compute_returns,
    compute_rsi,
    compute_volatility,
    compute_volume_change,
)
from app.services.history.schemas import Candle, Timeframe

logger = logging.getLogger(__name__)


async def get_latest_timestamp(
    session_factory: async_sessionmaker[AsyncSession],
    model: type,
    symbol: str,
    timeframe: Timeframe,
) -> datetime | None:
    async with session_factory() as session:
        return await session.scalar(
            select(model.timestamp)
            .where(model.symbol == symbol, model.timeframe == timeframe.value)
            .order_by(model.timestamp.desc())
            .limit(1)
        )


async def upsert_candles(
    session_factory: async_sessionmaker[AsyncSession], model: type, candles: list[Candle]
) -> int:
    """Inserts candles, silently skipping any that already exist for
    (symbol, timeframe, timestamp) -- the unique constraint is the single
    source of truth for "is this a duplicate", so re-running a sync over an
    already-covered range is always safe."""
    if not candles:
        return 0

    rows = [
        {
            "symbol": c.symbol,
            "timeframe": c.timeframe.value,
            "timestamp": c.timestamp,
            "open": c.open,
            "high": c.high,
            "low": c.low,
            "close": c.close,
            "volume": c.volume,
            "source": c.source,
        }
        for c in candles
    ]

    async with session_factory() as session:
        stmt = pg_insert(model).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=["symbol", "timeframe", "timestamp"])
        result = await session.execute(stmt)
        await session.commit()
        return result.rowcount or 0


async def get_series(
    session_factory: async_sessionmaker[AsyncSession],
    model: type,
    symbol: str,
    timeframe: Timeframe,
) -> list:
    async with session_factory() as session:
        result = await session.scalars(
            select(model)
            .where(model.symbol == symbol, model.timeframe == timeframe.value)
            .order_by(model.timestamp.asc())
        )
        return list(result)


async def fill_missing_indicators(
    session_factory: async_sessionmaker[AsyncSession],
    model: type,
    symbol: str,
    timeframe: Timeframe,
) -> int:
    """Computes indicators over the full stored series but only writes rows
    that have never been computed before (`indicators_computed=False`) --
    the calculations are never redone for a row once they've been saved."""
    rows = await get_series(session_factory, model, symbol, timeframe)
    if not rows:
        return 0

    closes = [float(r.close) for r in rows]
    highs = [float(r.high) for r in rows]
    lows = [float(r.low) for r in rows]
    volumes = [float(r.volume) if r.volume is not None else None for r in rows]

    returns = compute_returns(closes)
    volatility = compute_volatility(returns)
    atr = compute_atr(highs, lows, closes)
    rsi = compute_rsi(closes)
    macd, macd_signal, macd_histogram = compute_macd(closes)
    moving_averages = compute_moving_averages(closes)
    volume_change = compute_volume_change(volumes)

    updates = [
        {
            "id": row.id,
            "return_pct": returns[i],
            "volatility": volatility[i],
            "atr": atr[i],
            "rsi": rsi[i],
            "macd": macd[i],
            "macd_signal": macd_signal[i],
            "macd_histogram": macd_histogram[i],
            "sma_20": moving_averages[20][i],
            "sma_50": moving_averages[50][i],
            "sma_200": moving_averages[200][i],
            "volume_change_pct": volume_change[i],
            "indicators_computed": True,
        }
        for i, row in enumerate(rows)
        if not row.indicators_computed
    ]

    if not updates:
        return 0

    async with session_factory() as session:
        await session.execute(update(model), updates)
        await session.commit()
    return len(updates)
