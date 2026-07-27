#!/usr/bin/env python
"""CLI entrypoint for the Historical Intelligence Engine.

    python sync_history.py                        # sync everything, 10y lookback
    python sync_history.py --years 5
    python sync_history.py --symbol BTC --timeframe 1d
    python sync_history.py --validate-only         # skip sync, just validate + repair
    python sync_history.py --no-repair              # report gaps/duplicates without fixing them
    python sync_history.py --seed-events            # load the curated historical-events seed
    python sync_history.py --sync-calendar           # sync FRED release dates + FOMC seed

Builds a resumable historical OHLCV + indicator database (daily/4h/1h) for
crypto, US equities/indices and macro indicators, then validates the result
for gaps and duplicates and repairs what it can. See README for full data
coverage and known source limitations.
"""

import argparse
import asyncio
import logging

from app.database.session import get_session_factory
from app.services.calendar.engine import EconomicCalendarEngine
from app.services.history.events import seed_events
from app.services.history.pipeline import run_sync, run_validation
from app.services.history.registry import HistorySymbolConfig, build_registry
from app.services.history.schemas import Timeframe
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
    parser.add_argument(
        "--sync-calendar",
        action="store_true",
        help="Sync FRED release dates + the curated FOMC seed and exit",
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


async def _run(args: argparse.Namespace) -> None:
    if args.seed_events:
        inserted = await seed_events(get_session_factory())
        logger.info("Seeded %d historical event(s)", inserted)
        return

    if args.sync_calendar:
        engine = EconomicCalendarEngine(get_session_factory())
        inserted = await engine.sync_fred_releases()
        inserted += await engine.seed_central_bank_meetings()
        logger.info("Synced %d economic calendar event(s)", inserted)
        return

    registry = _filter_registry(build_registry(), args.symbol, args.timeframe)
    session_factory = get_session_factory()

    if not args.validate_only:
        await run_sync(session_factory, registry, args.years)

    await run_validation(session_factory, registry, repair=not args.no_repair)


def main() -> None:
    configure_logging("INFO")
    asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    main()
