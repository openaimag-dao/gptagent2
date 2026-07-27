import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.history.registry import HistorySymbolConfig
from app.services.history.repair import repair_duplicates, repair_gaps
from app.services.history.repository import get_series
from app.services.history.sync import HistorySyncEngine
from app.services.history.validation import find_duplicate_timestamps, find_gaps

logger = logging.getLogger(__name__)


async def run_sync(
    session_factory: async_sessionmaker[AsyncSession],
    registry: list[HistorySymbolConfig],
    years: int,
) -> None:
    """Fetches `years` of OHLCV+indicators for every symbol/timeframe in `registry`."""
    engine = HistorySyncEngine(session_factory, registry=registry)
    outcomes = await engine.sync_all(lookback_years=years)
    for outcome in outcomes:
        if outcome.error:
            logger.error("%s/%s FAILED: %s", outcome.symbol, outcome.timeframe.value, outcome.error)
        else:
            logger.info(
                "%s/%s: fetched %d, inserted %d, indicators computed for %d rows",
                outcome.symbol,
                outcome.timeframe.value,
                outcome.candles_fetched,
                outcome.candles_inserted,
                outcome.indicators_computed,
            )


async def run_validation(
    session_factory: async_sessionmaker[AsyncSession],
    registry: list[HistorySymbolConfig],
    *,
    repair: bool = True,
) -> None:
    """Checks every symbol/timeframe's stored data for gaps/duplicates and
    repairs what it can."""
    for config in registry:
        for timeframe in config.timeframes:
            rows = await get_series(session_factory, config.model, config.symbol, timeframe)
            if not rows:
                continue
            timestamps = [row.timestamp for row in rows]

            duplicates = find_duplicate_timestamps(timestamps)
            if duplicates:
                logger.warning(
                    "%s/%s: %d duplicate candle(s) found",
                    config.symbol,
                    timeframe.value,
                    len(duplicates),
                )
                if repair:
                    removed = await repair_duplicates(
                        session_factory, config.model, config.symbol, timeframe
                    )
                    logger.info(
                        "%s/%s: removed %d duplicate row(s)",
                        config.symbol,
                        timeframe.value,
                        removed,
                    )

            gaps = find_gaps(sorted(set(timestamps)), timeframe, config.market)
            if gaps:
                logger.warning(
                    "%s/%s: %d gap(s) detected", config.symbol, timeframe.value, len(gaps)
                )
                if repair:
                    inserted = await repair_gaps(session_factory, config, timeframe, gaps)
                    logger.info(
                        "%s/%s: backfilled %d candle(s) across gaps",
                        config.symbol,
                        timeframe.value,
                        inserted,
                    )


async def sync_and_validate(
    session_factory: async_sessionmaker[AsyncSession],
    registry: list[HistorySymbolConfig],
    years: int,
    *,
    repair: bool = True,
) -> None:
    """Runs a full sync followed by validation+repair.

    Shared by sync_history.py (CLI, when not --validate-only) and the admin
    API endpoint that triggers the same pipeline against a running
    deployment, so the two never drift.
    """
    await run_sync(session_factory, registry, years)
    await run_validation(session_factory, registry, repair=repair)
