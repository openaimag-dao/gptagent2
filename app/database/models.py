import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Numeric, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class AssetClass(str, enum.Enum):
    CRYPTO = "crypto"
    STOCK = "stock"
    INDEX = "index"
    MACRO = "macro"


class SnapshotBatch(Base):
    """A single market-data collection run. Groups every AssetPrice fetched together."""

    __tablename__ = "snapshot_batches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    asset_prices: Mapped[list["AssetPrice"]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )


class AssetPrice(Base):
    """A single asset quote (crypto / stock / index / macro indicator) captured in a batch."""

    __tablename__ = "asset_prices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    batch_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(), ForeignKey("snapshot_batches.id", ondelete="CASCADE"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(100))
    asset_class: Mapped[AssetClass] = mapped_column(
        Enum(
            AssetClass,
            name="asset_class",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        )
    )
    price: Mapped[float] = mapped_column(Numeric(24, 8))
    change_24h: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    change_pct_24h: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Numeric(30, 2), nullable=True)
    volume_24h: Mapped[float | None] = mapped_column(Numeric(30, 2), nullable=True)
    source: Mapped[str] = mapped_column(String(50))
    extra: Mapped[dict] = mapped_column(JSON, default=dict)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )

    batch: Mapped["SnapshotBatch"] = relationship(back_populates="asset_prices")


class NewsCategory(str, enum.Enum):
    FEDERAL_RESERVE = "federal_reserve"
    SEC = "sec"
    ETF = "etf"
    CRYPTO = "crypto"
    STOCKS = "stocks"
    MACRO = "macro"


class NewsSentiment(str, enum.Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class NewsItem(Base):
    """A single deduplicated, sentiment-classified news item."""

    __tablename__ = "news_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(50), index=True)
    category: Mapped[NewsCategory] = mapped_column(
        Enum(
            NewsCategory,
            name="news_category",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(1000), unique=True, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    sentiment: Mapped[NewsSentiment] = mapped_column(
        Enum(
            NewsSentiment,
            name="news_sentiment",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        )
    )
    sentiment_score: Mapped[float] = mapped_column(Numeric(6, 2))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
