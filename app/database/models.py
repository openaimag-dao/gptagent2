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
    BULL = "bull"
    BEAR = "bear"
    ACCUMULATION = "accumulation"
    DISTRIBUTION = "distribution"
    CAPITULATION = "capitulation"
    RECOVERY = "recovery"
    SIDEWAYS = "sideways"


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
    # Raw (never LLM-generated) Global Market Score + ETF flow proxy + Whale
    # Intelligence snapshots that grounded this report's prompt.
    institutional_summary: Mapped[dict] = mapped_column(JSON, default=dict)
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


class ForexHistory(_HistoryCandleMixin, Base):
    """OHLCV + indicator history for major forex pairs (EURUSD, GBPUSD, ...)."""

    __tablename__ = "forex_history"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", name="uq_forex_history_bar"),
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


class EconomicCalendarCategory(str, enum.Enum):
    CPI = "cpi"
    PPI = "ppi"
    NFP = "nfp"
    GDP = "gdp"
    FOMC = "fomc"
    ECB = "ecb"
    BOJ = "boj"
    PBOC = "pboc"


class EconomicCalendarEvent(Base):
    """A scheduled macro-data release or central-bank meeting date.

    Dates only -- no forecast/consensus/actual values, since there is no
    free, honest source for those (real consensus-forecast data is a paid
    product from vendors like Trading Economics/Investing.com). CPI/PPI/NFP/
    GDP dates come from FRED's release/dates API (FRED_API_KEY); FOMC/ECB/
    BOJ/PBOC dates come from each central bank's own published meeting
    calendar, curated the same way HistoricalEvent's seed data is.
    """

    __tablename__ = "economic_calendar_events"
    __table_args__ = (
        UniqueConstraint("category", "country", "event_date", name="uq_economic_calendar_event"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    category: Mapped[EconomicCalendarCategory] = mapped_column(
        Enum(
            EconomicCalendarCategory,
            name="economic_calendar_category",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        index=True,
    )
    country: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(200))
    importance: Mapped[str] = mapped_column(String(10))
    source: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class ProbabilitySnapshot(Base):
    """An empirical, historically-grounded probability read for one symbol/timeframe.

    Computed by bucketing the symbol's own stored RSI history and measuring
    what fraction of similar-RSI past occurrences were followed by a positive
    / negative / flat forward return -- never a fabricated or LLM-guessed
    number.
    """

    __tablename__ = "probability_snapshots"

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
    horizon_periods: Mapped[int] = mapped_column(default=1)
    reference_rsi: Mapped[float] = mapped_column(Numeric(6, 2))
    # The candle this prediction was made from -- lets the Self-Learning
    # Engine look up what actually happened `horizon_periods` later and
    # compare it against the prediction, instead of only ever guessing from
    # wall-clock `computed_at`.
    reference_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    sample_size: Mapped[int] = mapped_column()
    prob_up_pct: Mapped[int] = mapped_column()
    prob_down_pct: Mapped[int] = mapped_column()
    prob_flat_pct: Mapped[int] = mapped_column()
    avg_forward_return_pct: Mapped[float] = mapped_column(Numeric(10, 4))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class PatternDirection(str, enum.Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class PatternSignal(Base):
    """A detected technical pattern (candlestick or moving-average crossover)
    at a specific historical candle -- deterministic rule-based detection,
    stored once per (symbol, timeframe, timestamp, pattern_name)."""

    __tablename__ = "pattern_signals"

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
    pattern_name: Mapped[str] = mapped_column(String(50))
    direction: Mapped[PatternDirection] = mapped_column(
        Enum(
            PatternDirection,
            name="pattern_direction",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        )
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    __table_args__ = (
        UniqueConstraint(
            "symbol", "timeframe", "timestamp", "pattern_name", name="uq_pattern_signal"
        ),
    )


class GlobalMarketScore(Base):
    """A deterministic composite score (0-100 per sub-score) aggregating the
    live regime, signal and market snapshots -- see
    app/services/global_score/engine.py for the exact, documented formula
    behind every number here."""

    __tablename__ = "global_market_scores"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    risk_on_score: Mapped[int] = mapped_column()
    risk_off_score: Mapped[int] = mapped_column()
    liquidity_score: Mapped[int] = mapped_column()
    fear_score: Mapped[int] = mapped_column()
    greed_score: Mapped[int] = mapped_column()
    macro_pressure_score: Mapped[int] = mapped_column()
    institutional_activity_score: Mapped[int] = mapped_column()
    crypto_strength_score: Mapped[int] = mapped_column()
    stock_strength_score: Mapped[int] = mapped_column()
    global_score: Mapped[int] = mapped_column()
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class Portfolio(Base):
    """A named virtual portfolio -- no real brokerage integration, purely
    for tracking hypothetical exposure/risk against real live prices."""

    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    positions: Mapped[list["PortfolioPosition"]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )


class PortfolioPosition(Base):
    """One holding in a virtual portfolio. `entry_price` is optional (unrealized
    P&L is simply omitted when unknown, never guessed)."""

    __tablename__ = "portfolio_positions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    quantity: Mapped[float] = mapped_column(Numeric(24, 8))
    entry_price: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    portfolio: Mapped["Portfolio"] = relationship(back_populates="positions")


class AlertLog(Base):
    """Every Smart Alert Engine detection, broadcast or not -- `broadcast`
    records whether it actually cleared the conviction gate and was pushed
    to Telegram, so Market Memory has a full audit trail including
    near-misses, not just what users were actually notified about."""

    __tablename__ = "alert_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    alert_type: Mapped[str] = mapped_column(String(40), index=True)
    message: Mapped[str] = mapped_column(Text)
    conviction_tier: Mapped[str] = mapped_column(String(20))
    confidence_pct: Mapped[int] = mapped_column()
    broadcast: Mapped[bool] = mapped_column(default=False, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class ScenarioSnapshot(Base):
    """A set of named, probability-weighted forward scenarios (Soft Landing /
    Risk Off / Liquidity Expansion / Black Swan), deterministically derived
    from the Global Market Score at `computed_at` -- see
    app/services/scenarios/engine.py for the exact weighting formula."""

    __tablename__ = "scenario_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scenarios: Mapped[list] = mapped_column(JSON, default=list)
    global_score: Mapped[int] = mapped_column()
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class WhaleSnapshot(Base):
    """A persisted Whale Intelligence read -- including the honest
    "unavailable" responses, so Market Memory and the Smart Alert Engine
    have a real history of "we checked, no data source configured" rather
    than silently losing that information."""

    __tablename__ = "whale_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    available: Mapped[bool] = mapped_column(default=False)
    classification: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class EtfFlowSnapshot(Base):
    """A persisted ETF Intelligence read (news-sentiment proxy, never
    confirmed dollar flows -- see app/services/etf/engine.py). Stored so
    the Smart Alert Engine can detect a real change in classification over
    time instead of only ever comparing against a single in-memory call."""

    __tablename__ = "etf_flow_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    available: Mapped[bool] = mapped_column(default=False)
    classification: Mapped[str | None] = mapped_column(String(40), nullable=True)
    bullish_items: Mapped[int | None] = mapped_column(nullable=True)
    bearish_items: Mapped[int | None] = mapped_column(nullable=True)
    neutral_items: Mapped[int | None] = mapped_column(nullable=True)
    items_analyzed: Mapped[int] = mapped_column(default=0)
    window_hours: Mapped[int] = mapped_column(default=0)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class SentimentSnapshot(Base):
    """Sentiment Agent output: real Crypto Fear & Greed Index + news
    sentiment balance. Social (Twitter/X, Reddit) and options-market
    sentiment have no configured data source, so they're never blended into
    `global_sentiment_score` -- `social_sentiment_available` stays False and
    `social_sentiment_reason` explains why, every time."""

    __tablename__ = "sentiment_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    fear_greed_value: Mapped[int | None] = mapped_column(nullable=True)
    fear_greed_classification: Mapped[str | None] = mapped_column(String(30), nullable=True)
    news_sentiment_score: Mapped[int | None] = mapped_column(nullable=True)
    news_items_analyzed: Mapped[int] = mapped_column(default=0)
    social_sentiment_available: Mapped[bool] = mapped_column(default=False)
    social_sentiment_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    global_sentiment_score: Mapped[int | None] = mapped_column(nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class RuleCategory(str, enum.Enum):
    THEORY = "theory"
    RULE = "rule"
    MACRO_IDEA = "macro_idea"
    CRYPTO_IDEA = "crypto_idea"


class KnowledgeRule(Base):
    """A user-submitted trading theory/rule, automatically backtested against
    real stored history (see app/services/knowledge/rules.py and
    app/services/backtest/). Backtest columns stay NULL until the first
    backtest run completes."""

    __tablename__ = "knowledge_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[RuleCategory] = mapped_column(
        Enum(
            RuleCategory,
            name="rule_category",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        index=True,
    )
    author: Mapped[str] = mapped_column(String(100))
    target_symbol: Mapped[str] = mapped_column(String(20), index=True)
    conditions: Mapped[list] = mapped_column(JSON, default=list)
    horizon_periods: Mapped[int] = mapped_column(default=1)

    occurrences: Mapped[int | None] = mapped_column(nullable=True)
    win_rate_pct: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    avg_return_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    max_drawdown_pct: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    profit_factor: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    sharpe_ratio: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    confidence_pct: Mapped[int | None] = mapped_column(nullable=True)
    last_backtested_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class SimilarMarketMatch(Base):
    """One stored comparison from the Similar Market Engine: a historical
    date whose technical conditions matched a symbol's conditions as of
    `reference_timestamp`, plus what actually happened next."""

    __tablename__ = "similar_market_matches"

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
    reference_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    match_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    similarity_score: Mapped[float] = mapped_column(Numeric(6, 2))
    market_regime: Mapped[str | None] = mapped_column(String(30), nullable=True)
    btc_result_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    nasdaq_result_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    forward_return_1d_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    forward_return_3d_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    forward_return_7d_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    forward_return_30d_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class FeatureSnapshot(Base):
    """A computed-feature read for one symbol -- momentum/beta/cointegration/
    market breadth/funding momentum/OI change (see app/services/features/).
    Stored as a flexible JSON blob (like SignalSnapshot.factors and
    MarketRegimeSnapshot.inputs) since the feature set grows over time and a
    fixed-column table would need a migration for every addition -- each key
    present means that feature was actually computable this cycle, an
    absent key means it honestly wasn't (never a fabricated 0/null value)."""

    __tablename__ = "feature_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
