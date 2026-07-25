from abc import ABC, abstractmethod
from datetime import datetime

from app.services.history.schemas import Candle, Timeframe


class HistoricalDataProvider(ABC):
    """A single historical data source, fetching OHLCV candles for one symbol/timeframe."""

    name: str

    @abstractmethod
    async def fetch_candles(
        self, symbol: str, timeframe: Timeframe, since: datetime | None
    ) -> list[Candle]:
        """Returns candles at or after `since`, oldest first.

        `since=None` means "as much history as the source will give us".
        """
        raise NotImplementedError
