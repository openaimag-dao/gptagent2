import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
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


class Correlation(Base):
    """A rolling Pearson correlation between two symbols' daily returns over one window."""

    __tablename__ = "correlations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol_a: Mapped[str] = mapped_column(String(20), index=True)
    symbol_b: Mapped[str] = mapped_column(String(20), index=True)
    window_days: Mapped[int] = mapped_column()
    correlation: Mapped[float] = mapped_column(Numeric(6, 4))
    data_points: Mapped[int] = mapped_column()
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class MarketRegimeType(str, enum.Enum):
    RISK_ON = "risk_on"
    RISK_OFF = "risk_off"
    NEUTRAL = "neutral"
    LIQUIDITY_EXPANSION = "liquidity_expansion"
    LIQUIDITY_CONTRACTION = "liquidity_contraction"
    FLIGHT_TO_SAFETY = "flight_to_safety"


class MarketRegimeSnapshot(Base):
    """The detected market regime at a point in time, with the inputs that drove it."""

    __tablename__ = "market_regime_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    regime: Mapped[MarketRegimeType] = mapped_column(
        Enum(
            MarketRegimeType,
            name="market_regime_type",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        )
    )
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class SignalSnapshot(Base):
    """A Bull/Bear signal score computed from the weighted factor table."""

    __tablename__ = "signal_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    bull_score: Mapped[int] = mapped_column()
    bear_score: Mapped[int] = mapped_column()
    net_score: Mapped[int] = mapped_column()
    confidence_pct: Mapped[int] = mapped_column()
    factors: Mapped[dict] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class Report(Base):
    """A full AI-generated market intelligence report: raw data + LLM narrative."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(), primary_key=True, default=uuid.uuid4)
    report_type: Mapped[str] = mapped_column(String(30), index=True)
    regime: Mapped[str] = mapped_column(String(30))
    risk_level: Mapped[str] = mapped_column(String(20))
    bull_score: Mapped[int] = mapped_column()
    bear_score: Mapped[int] = mapped_column()
    confidence_pct: Mapped[int] = mapped_column()
    market_summary: Mapped[dict] = mapped_column(JSON, default=dict)
    correlations_summary: Mapped[list] = mapped_column(JSON, default=list)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class HistoryTimeframe(str, enum.Enum):
    DAILY = "1d"
    FOUR_HOUR = "4h"
    ONE_HOUR = "1h"


class _HistoryCandleMixin:
    """Shared OHLCV + indicator columns for the market/crypto/stock/macro history tables.

    Indicators are computed once by the sync engine and persisted here rather
    than recomputed on read -- `indicators_computed` marks that a row has
    already been through indicator calculation so a re-sync never redoes it.
    """

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[HistoryTimeframe] = mapped_column(
        Enum(
            HistoryTimeframe,
            name="history_timeframe",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        index=True,
    )
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    open: Mapped[float] = mapped_column(Numeric(24, 8))
    high: Mapped[float] = mapped_column(Numeric(24, 8))
    low: Mapped[float] = mapped_column(Numeric(24, 8))
    close: Mapped[float] = mapped_column(Numeric(24, 8))
    volume: Mapped[float | None] = mapped_column(Numeric(30, 2), nullable=True)

    return_pct: Mapped[float | None] = mapped_column(Numeric(14, 8), nullable=True)
    volatility: Mapped[float | None] = mapped_column(Numeric(14, 8), nullable=True)
    atr: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    rsi: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    macd: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    macd_signal: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    macd_histogram: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    sma_20: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    sma_50: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    sma_200: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    volume_change_pct: Mapped[float | None] = mapped_column(Numeric(14, 8), nullable=True)
    indicators_computed: Mapped[bool] = mapped_column(default=False, index=True)

    source: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class MarketHistory(_HistoryCandleMixin, Base):
    """OHLCV + indicator history for broad market indices (NASDAQ, S&P 500, Dow, Russell 2000)."""

    __tablename__ = "market_history"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_market_history_bar"),
    )


class CryptoHistory(_HistoryCandleMixin, Base):
    """OHLCV + indicator history for crypto assets (BTC, ETH, SOL)."""

    __tablename__ = "crypto_history"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_crypto_history_bar"),
    )


class StockHistory(_HistoryCandleMixin, Base):
    """OHLCV + indicator history for individual equities (the Magnificent 7)."""

    __tablename__ = "stock_history"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_stock_history_bar"),
    )


class MacroHistory(_HistoryCandleMixin, Base):
    """OHLCV(-equivalent) + indicator history for macro indicators.

    Single-value series (Fed Rate, CPI, M2, yields sourced from FRED) are
    stored with open == high == low == close == the observed value -- a
    standard adaptation that keeps ATR/RSI/MACD computable uniformly across
    every history table without a separate code path for non-OHLC sources.
    """

    __tablename__ = "macro_history"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_macro_history_bar"),
    )


class HistoricalEventCategory(str, enum.Enum):
    HALVING = "halving"
    CRASH = "crash"
    MACRO_POLICY = "macro_policy"
    REGULATORY = "regulatory"
    BLACK_SWAN = "black_swan"


class HistoricalEvent(Base):
    """A curated, factual market-moving event, giving the AI historical context."""

    __tablename__ = "historical_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    title: Mapped[str] = mapped_column(String(200))
    category: Mapped[HistoricalEventCategory] = mapped_column(
        Enum(
            HistoricalEventCategory,
            name="historical_event_category",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        index=True,
    )
    description: Mapped[str] = mapped_column(Text)
    symbols_affected: Mapped[list] = mapped_column(JSON, default=list)
    source: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
