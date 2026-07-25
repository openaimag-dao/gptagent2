#!/usr/bin/env python
"""CLI entrypoint for the Historical Intelligence Engine.

    python sync_history.py                        # sync everything, 10y lookback
    python sync_history.py --years 5
    python sync_history.py --symbol BTC --timeframe 1d
    python sync_history.py --validate-only         # skip sync, just validate + repair
    python sync_history.py --no-repair              # report gaps/duplicates without fixing them
    python sync_history.py --seed-events            # load the curated historical-events seed

Builds a resumable historical OHLCV + indicator database (daily/4h/1h) for
crypto, US equities/indices and macro indicators, then validates the result
for gaps and duplicates and repairs what it can. See README for full data
coverage and known source limitations.
"""

import argparse
import asyncio
import logging

from app.database.session import get_session_factory
from app.services.history.events import seed_events
from app.services.history.registry import HistorySymbolConfig, build_registry
from app.services.history.repair import repair_duplicates, repair_gaps
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.history.sync import HistorySyncEngine
from app.services.history.validation import find_duplicate_timestamps, find_gaps
from app.utils.logging import configure_logging

logger = logging.getLogger("sync_history")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync the historical intelligence database.")
    parser.add_argument(
        "--years", type=int, default=10, help="Lookback window in years (default: 10)"
    )
    parser.add_argument("--symbol", type=str, default=None, help="Only sync this symbol (e.g. BTC)")
    parser.add_argument(
        "--timeframe", type=str, choices=[tf.value for tf in Timeframe], default=None
    )
    parser.add_argument(
        "--validate-only", action="store_true", help="Skip sync, only validate + repair stored data"
    )
    parser.add_argument(
        "--no-repair", action="store_true", help="Report gaps/duplicates without repairing them"
    )
    parser.add_argument(
        "--seed-events",
        action="store_true",
        help="Load the curated historical-events seed and exit",
    )
    return parser.parse_args()


def _filter_registry(
    registry: list[HistorySymbolConfig], symbol: str | None, timeframe_arg: str | None
) -> list[HistorySymbolConfig]:
    if symbol:
        registry = [c for c in registry if c.symbol == symbol.upper()]
        if not registry:
            raise SystemExit(f"Unknown symbol: {symbol}")
    if timeframe_arg:
        timeframe = Timeframe(timeframe_arg)
        registry = [
            HistorySymbolConfig(
                c.symbol,
                c.model,
                c.provider,
                tuple(tf for tf in c.timeframes if tf == timeframe),
                c.market,
            )
            for c in registry
        ]
        registry = [c for c in registry if c.timeframes]
        if not registry:
            raise SystemExit(f"No symbols support timeframe {timeframe_arg}")
    return registry


async def _run_sync(registry: list[HistorySymbolConfig], years: int) -> None:
    engine = HistorySyncEngine(get_session_factory(), registry=registry)
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


async def _run_validation(registry: list[HistorySymbolConfig], repair: bool) -> None:
    session_factory = get_session_factory()
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


async def _run(args: argparse.Namespace) -> None:
    if args.seed_events:
        inserted = await seed_events(get_session_factory())
        logger.info("Seeded %d historical event(s)", inserted)
        return

    registry = _filter_registry(build_registry(), args.symbol, args.timeframe)

    if not args.validate_only:
        await _run_sync(registry, args.years)

    await _run_validation(registry, repair=not args.no_repair)


def main() -> None:
    configure_logging("INFO")
    asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    main()
