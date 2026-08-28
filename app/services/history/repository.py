import logging
from datetime import datetime

from sqlalchemy import delete, select, update
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
    session_factory: async_sessionmaker[AsyncSession],
    model: type,
    candles: list[Candle],
    *,
    do_update: bool = False,
) -> int:
    """Inserts candles. By default silently skips any that already exist for
    (symbol, timeframe, timestamp) -- the unique constraint is the single
    source of truth for "is this a duplicate", so re-running a sync over an
    already-covered range is always safe.

    `do_update=True` instead overwrites the OHLCV/source columns on
    conflict. Only meant for a timeframe that's *resampled* from another
    timeframe's freshly-fetched data on every single sync call (FOUR_HOUR,
    resampled from ONE_HOUR by every provider that supports it -- see
    providers/coingecko.py and providers/yfinance_provider.py) rather than
    fetched directly. A resampled bucket can legitimately start out
    incomplete: e.g. only one real hourly point has landed yet for a
    still-forming or just-elapsed 4h window, since the upstream provider's
    own "hourly" granularity is itself irregular near the live edge (not
    reliably 4 points per 4h window on the first sync that covers it). With
    the default DO NOTHING, that first incomplete value -- sometimes a
    fully flat open=high=low=close candle -- freezes there forever, even
    after later syncs' fetches contain the window's true, more complete
    hourly coverage; live-verified against production (12 of the last 180
    stored BTC 4h candles were stuck exactly this way, including ones
    several days old). DO UPDATE instead lets each bucket self-correct
    across the next few incremental syncs while it's still the newest
    stored row for that (symbol, timeframe) -- safe here specifically
    because a resampled candle is always recomputed fresh from the source
    data on every call, never accumulated state, so overwriting only ever
    moves it toward a more complete version of the same real data."""
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
        if do_update:
            stmt = stmt.on_conflict_do_update(
                index_elements=["symbol", "timeframe", "timestamp"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "source": stmt.excluded.source,
                },
            )
        else:
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


async def get_recent_series(
    session_factory: async_sessionmaker[AsyncSession],
    model: type,
    symbol: str,
    timeframe: Timeframe,
    limit: int,
) -> list:
    """Bounded read for API/chart consumers -- ORDER BY DESC LIMIT n at the
    database, not "fetch everything then slice in Python" (what get_series
    would do if reused here). Matters once 5m/15m rows exist: at 288
    candles/day/symbol, get_series's unbounded SELECT would load the whole
    history just to return the last `limit` rows every request.

    Deliberately a new function rather than a `limit` parameter on
    get_series -- fill_missing_indicators calls get_series and genuinely
    needs the *full* series for its recursive Wilder/EMA math; truncating
    that input window would silently change already-persisted indicator
    values for the remaining rows."""
    async with session_factory() as session:
        result = await session.scalars(
            select(model)
            .where(model.symbol == symbol, model.timeframe == timeframe.value)
            .order_by(model.timestamp.desc())
            .limit(limit)
        )
        return list(reversed(list(result)))


async def prune_candles(
    session_factory: async_sessionmaker[AsyncSession],
    model: type,
    symbol: str,
    timeframe: Timeframe,
    older_than: datetime,
) -> int:
    """Deletes rows strictly older than `older_than` for one (symbol,
    timeframe). Used for the realtime-aggregated 5m/15m timeframes, which
    have no natural upper bound on row count (288 candles/day/symbol) --
    deleting old rows here, rather than truncating the *input* window
    fill_missing_indicators sees, is what preserves already-persisted
    indicator values on the rows that remain: Wilder RSI/ATR and MACD's
    EMAs are recursive, so shrinking their input window would silently
    change values already saved for newer rows."""
    async with session_factory() as session:
        result = await session.execute(
            delete(model).where(
                model.symbol == symbol,
                model.timeframe == timeframe.value,
                model.timestamp < older_than,
            )
        )
        await session.commit()
        return result.rowcount or 0


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
