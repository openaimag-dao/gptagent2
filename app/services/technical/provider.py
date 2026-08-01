"""TechnicalAnalysisProvider -- the "Provider Layer" step: TradingView MCP
-> Adapter -> Normalizer -> **Provider Layer** -> Event Bus -> Existing
Engines. TradingView MCP (app.services.technical.tradingview_client) is
tried first when configured and preferred for every timeframe it answers;
this project's own synced OHLCV history is the honest fallback for the
three natively-stored timeframes plus a derived weekly candle -- matching
the multi-source-with-fallback shape every other optional provider in this
project already uses (MultiSourceMacroProvider, WhaleIntelligenceEngine).

Timeframe reality, stated plainly rather than faked: this project synced
OHLCV history at 1h/4h/1d only (app.services.history.registry) -- 1W is
derived by resampling stored daily candles (resampling.py); 1m/5m/15m/30m
have no local data at all and are only ever answered by TradingView MCP,
honestly `None` otherwise.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.history.registry import find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.technical.normalizer import (
    NormalizedIndicators,
    normalize_local,
    normalize_tradingview,
)
from app.services.technical.resampling import resample_to_weekly
from app.services.technical.tradingview_client import TradingViewMCPClient

logger = logging.getLogger(__name__)

# Every window the mission asks for; only a subset is honestly answerable
# without TradingView MCP configured (see module docstring).
ALL_TIMEFRAME_LABELS: tuple[str, ...] = ("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w")
LOCAL_NATIVE_TIMEFRAMES: dict[str, Timeframe] = {
    "1h": Timeframe.ONE_HOUR,
    "4h": Timeframe.FOUR_HOUR,
    "1d": Timeframe.DAILY,
}
INTRADAY_TRADINGVIEW_ONLY: tuple[str, ...] = ("1m", "5m", "15m", "30m")


class TechnicalAnalysisProvider:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        tradingview_client: TradingViewMCPClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._tradingview_client = tradingview_client or TradingViewMCPClient()

    async def _try_tradingview(
        self, symbol: str, timeframe_label: str
    ) -> NormalizedIndicators | None:
        if not self._tradingview_client.configured:
            return None
        raw = await self._tradingview_client.fetch_indicators(symbol, timeframe_label)
        if raw is None:
            return None
        return normalize_tradingview(symbol, timeframe_label, raw)

    async def _local_native(self, symbol: str, timeframe_label: str) -> NormalizedIndicators | None:
        config = find_symbol_config(symbol)
        timeframe = LOCAL_NATIVE_TIMEFRAMES[timeframe_label]
        if config is None or timeframe not in config.timeframes:
            return None
        rows = await get_series(self._session_factory, config.model, symbol, timeframe)
        return normalize_local(symbol, timeframe_label, rows)

    async def _local_weekly(self, symbol: str) -> NormalizedIndicators | None:
        config = find_symbol_config(symbol)
        if config is None or Timeframe.DAILY not in config.timeframes:
            return None
        daily_rows = await get_series(self._session_factory, config.model, symbol, Timeframe.DAILY)
        weekly_rows = resample_to_weekly(daily_rows)
        return normalize_local(symbol, "1w", weekly_rows)

    async def get_indicators(
        self, symbol: str, timeframe_label: str
    ) -> NormalizedIndicators | None:
        symbol = symbol.upper()
        if timeframe_label not in ALL_TIMEFRAME_LABELS:
            raise ValueError(
                f"Unknown timeframe {timeframe_label!r}; expected one of {ALL_TIMEFRAME_LABELS}"
            )

        tradingview_reading = await self._try_tradingview(symbol, timeframe_label)
        if tradingview_reading is not None:
            return tradingview_reading

        if timeframe_label in INTRADAY_TRADINGVIEW_ONLY:
            return None  # no local intraday history exists at any resolution
        if timeframe_label == "1w":
            return await self._local_weekly(symbol)
        return await self._local_native(symbol, timeframe_label)

    async def get_daily_pair(
        self, symbol: str
    ) -> tuple[NormalizedIndicators | None, NormalizedIndicators | None]:
        """(current, previous) daily readings for cross-signal detection
        (Golden/Death Cross, MACD crossover) -- "previous" is the same
        stored series minus its most recent candle, not a second fetch.
        Local-only: TradingView MCP answers a point-in-time snapshot, not a
        laggable series, so cross detection isn't attempted against it."""
        symbol = symbol.upper()
        config = find_symbol_config(symbol)
        if config is None or Timeframe.DAILY not in config.timeframes:
            return None, None
        rows = await get_series(self._session_factory, config.model, symbol, Timeframe.DAILY)
        current = normalize_local(symbol, "1d", rows)
        previous = normalize_local(symbol, "1d", rows[:-1]) if len(rows) > 1 else None
        return current, previous

    async def get_multi_timeframe(
        self, symbol: str, timeframe_labels: tuple[str, ...] = ("1h", "4h", "1d", "1w")
    ) -> dict[str, NormalizedIndicators | None]:
        """Readings across several timeframes for one symbol -- the input to
        the multi-timeframe combination in scoring.py. Defaults to the four
        timeframes honestly answerable without TradingView MCP configured;
        pass the full 8-window set once a real MCP endpoint is wired in."""
        return {label: await self.get_indicators(symbol, label) for label in timeframe_labels}
