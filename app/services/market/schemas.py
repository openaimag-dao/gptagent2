import enum
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AssetClass(str, enum.Enum):
    CRYPTO = "crypto"
    STOCK = "stock"
    INDEX = "index"
    MACRO = "macro"


class AssetQuote(BaseModel):
    """A single normalized market quote, regardless of provider or asset type."""

    symbol: str
    name: str
    asset_class: AssetClass
    price: float
    change_24h: float | None = None
    change_pct_24h: float | None = None
    market_cap: float | None = None
    volume_24h: float | None = None
    source: str
    extra: dict[str, Any] = Field(default_factory=dict)


class MarketSnapshotResult(BaseModel):
    """The outcome of one aggregator collection run across all providers."""

    batch_id: uuid.UUID
    collected_at: datetime
    quotes: list[AssetQuote]
    errors: list[str] = Field(default_factory=list)
