import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.history.registry import HistorySymbolConfig, build_registry
from app.services.history.repository import (
    fill_missing_indicators,
    get_latest_timestamp,
    upsert_candles,
)
from app.services.history.schemas import Timeframe

logger = logging.getLogger(__name__)


@dataclass
class SyncOutcome:
    symbol: str
    timeframe: Timeframe
    candles_fetched: int = 0
    candles_inserted: int = 0
    indicators_computed: int = 0
    error: str | None = None


class HistorySyncEngine:
    """Backfills and incrementally updates the historical intelligence database.

    Resumable by design: each (symbol, timeframe) sync only asks its provider
    for candles after the latest timestamp already stored, so re-running the
    sync never re-fetches or re-computes data it already has.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        registry: list[HistorySymbolConfig] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._registry = registry if registry is not None else build_registry()

    async def sync_symbol_timeframe(
        self, config: HistorySymbolConfig, timeframe: Timeframe, lookback_years: int
    ) -> SyncOutcome:
        earliest_allowed = datetime.now(UTC) - timedelta(days=lookback_years * 365)
        latest_stored = await get_latest_timestamp(
            self._session_factory, config.model, config.symbol, timeframe
        )
        since = latest_stored if latest_stored is not None else earliest_allowed

        candles = await config.provider.fetch_candles(config.symbol, timeframe, since)
        inserted = await upsert_candles(self._session_factory, config.model, candles)
        indicators_computed = await fill_missing_indicators(
            self._session_factory, config.model, config.symbol, timeframe
        )

        return SyncOutcome(
            symbol=config.symbol,
            timeframe=timeframe,
            candles_fetched=len(candles),
            candles_inserted=inserted,
            indicators_computed=indicators_computed,
        )

    async def sync_all(self, lookback_years: int = 10) -> list[SyncOutcome]:
        """One symbol/timeframe failing (rate limit, missing API key, network
        blip) never aborts the rest of the sync -- it's recorded and skipped,
        matching the fault-tolerant pattern used by MarketDataAggregator."""
        outcomes: list[SyncOutcome] = []
        for config in self._registry:
            for timeframe in config.timeframes:
                try:
                    outcomes.append(
                        await self.sync_symbol_timeframe(config, timeframe, lookback_years)
                    )
                except Exception as exc:
                    logger.warning(
                        "History sync failed for %s/%s: %s", config.symbol, timeframe.value, exc
                    )
                    outcomes.append(
                        SyncOutcome(symbol=config.symbol, timeframe=timeframe, error=str(exc))
                    )
        return outcomes
