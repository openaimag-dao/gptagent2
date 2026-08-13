"""Generic primary/fallback composition for HistoricalDataProvider.

Tries `primary` first; only calls `fallback` when primary returns zero
candles. yfinance's own provider returns [] rather than raising when Yahoo
Finance blocks/rate-limits a request (its known operational failure mode --
see YFinanceHistoricalProvider's docstring), so "empty" rather than
"raised" is the right trigger. Never prefers the fallback over a working
primary: if yfinance's block ever lifts, this automatically goes back to
using it with no code change.
"""

import logging
from datetime import datetime

from app.services.history.base import HistoricalDataProvider
from app.services.history.schemas import Candle, Timeframe

logger = logging.getLogger(__name__)


class FallbackHistoricalProvider(HistoricalDataProvider):
    def __init__(self, primary: HistoricalDataProvider, fallback: HistoricalDataProvider) -> None:
        self._primary = primary
        self._fallback = fallback
        self.name = f"{primary.name}+{fallback.name}_fallback"

    async def fetch_candles(
        self, symbol: str, timeframe: Timeframe, since: datetime | None
    ) -> list[Candle]:
        try:
            candles = await self._primary.fetch_candles(symbol, timeframe, since)
        except Exception:
            logger.warning(
                "%s raised for %s/%s, trying fallback",
                self._primary.name,
                symbol,
                timeframe.value,
                exc_info=True,
            )
            candles = []
        if candles:
            return candles

        logger.info(
            "%s returned no candles for %s/%s, trying %s",
            self._primary.name,
            symbol,
            timeframe.value,
            self._fallback.name,
        )
        return await self._fallback.fetch_candles(symbol, timeframe, since)
