import enum
from datetime import datetime

from pydantic import BaseModel


class Timeframe(str, enum.Enum):
    DAILY = "1d"
    FOUR_HOUR = "4h"
    ONE_HOUR = "1h"
    # Realtime-aggregated (Futures Simulator chart) -- see
    # app/services/realtime/aggregator.py and registry.py's
    # realtime_timeframes. Not part of any provider's fetchable timeframes.
    FIFTEEN_MINUTE = "15m"
    FIVE_MINUTE = "5m"


class Candle(BaseModel):
    """One OHLCV bar for a symbol at a given timeframe, UTC candle-open timestamp."""

    symbol: str
    timeframe: Timeframe
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None = None
    source: str
