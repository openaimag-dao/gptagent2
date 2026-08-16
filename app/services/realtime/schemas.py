import enum
from datetime import datetime

from pydantic import BaseModel


class ConnectionStatus(str, enum.Enum):
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    OFFLINE = "offline"


class RealtimePriceTick(BaseModel):
    """A single normalized realtime price update, regardless of exchange."""

    symbol: str
    price: float
    change_24h: float | None = None
    change_pct_24h: float | None = None
    volume_24h: float | None = None
    high_24h: float | None = None
    low_24h: float | None = None
    source: str = "binance"
    # When the exchange generated this tick, vs. when our collector
    # processed it -- the gap between the two is real network/processing
    # latency, not fabricated.
    event_timestamp: datetime
    received_at: datetime
