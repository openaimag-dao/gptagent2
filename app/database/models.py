import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    Enum,
    ForeignKey,
    Index,
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
    STRONG_BULL = "strong_bull"
    BULL_WEAKENING = "bull_weakening"
    ALTSEASON = "altseason"


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
    # 0-100: how much of the deciding cross-asset evidence was actually
    # present when this regime was detected (see compute_regime_confidence).
    # Nullable so pre-existing rows are honestly "unavailable", never
    # backfilled with a guessed number.
    confidence_pct: Mapped[int | None] = mapped_column(nullable=True)
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
    # Empirical forward-return distribution (percentiles, in %) across the
    # same matched sample avg_forward_return_pct is the mean of -- the
    # spread of what actually happened, not just its average. Nullable: a
    # snapshot from before this column existed, or one whose sample was too
    # small to compute quantiles from, stays honestly None.
    p10_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    p25_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    p50_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    p75_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    p90_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    # Whether the match sample was actually filtered by market regime (see
    # compute_rsi_probability's regime_series/reference_regime params), and
    # which regime it was filtered to -- honest even when the caller asked
    # for regime-conditioning but there wasn't enough same-regime history
    # and it fell back to the RSI-only sample.
    regime_conditioned: Mapped[bool] = mapped_column(default=False)
    reference_regime: Mapped[str | None] = mapped_column(String(30), nullable=True)
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
    # Nullable: honestly None when the underlying data (30d momentum for
    # trend_strength_score) hasn't been computed yet this cycle, rather
    # than a fabricated neutral default.
    trend_strength_score: Mapped[int | None] = mapped_column(nullable=True)
    risk_score: Mapped[int | None] = mapped_column(nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(nullable=True)
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


class AlertRule(Base):
    """A user-defined threshold rule (v4.0 Phase 8 "Configurable Alerts"),
    complementing rather than replacing the Smart Alert Engine's fixed
    detectors above: those fire on deltas the platform decided matter
    (regime changes, flash moves, ...); this fires when a metric the user
    picked crosses a threshold the user picked, and notifies only that
    user's chat rather than every broadcast chat. There is no user/auth
    model in this platform, so `chat_id` (the owning Telegram chat) is the
    only ownership key."""

    __tablename__ = "alert_rules"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[str] = mapped_column(String(64), index=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    metric: Mapped[str] = mapped_column(String(30))
    operator: Mapped[str] = mapped_column(String(10))
    threshold: Mapped[float] = mapped_column(Numeric(24, 8))
    cooldown_minutes: Mapped[int] = mapped_column(default=60)
    enabled: Mapped[bool] = mapped_column(default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AgentPredictionLog(Base):
    """Every specialist agent's direction/confidence call, logged each time
    the Consensus Engine runs, so those calls can later be checked against
    what actually happened (see app/services/reliability/engine.py) --
    the same append-only, evaluate-once-the-horizon-elapses pattern
    LearningEngine already uses for ProbabilitySnapshot, applied to agents
    instead of probability predictions."""

    __tablename__ = "agent_prediction_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    agent: Mapped[str] = mapped_column(String(30), index=True)
    direction: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    reference_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    horizon_periods: Mapped[int] = mapped_column(default=1)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


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


class ResearchNote(Base):
    """The AI Researcher's daily note (V3 Phase 7): a write-up over that
    day's real, already-computed Smart Alert Engine detections (regime
    changes, correlation breaks, DXY reversals, derivatives-positioning
    swings, ETF sentiment shifts, liquidity swings, upcoming macro events)
    -- discovery/ranking is entirely deterministic (AlertLog rows ordered
    by their already-computed confidence_pct); the LLM is used only to
    narrate what was already found, never to invent or judge a discovery
    itself. `discoveries` is the exact ranked list the note was written
    from, so the note is always auditable against its real inputs."""

    __tablename__ = "research_notes"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    note: Mapped[str] = mapped_column(Text)
    discoveries: Mapped[list] = mapped_column(JSON, default=list)
    discovery_count: Mapped[int] = mapped_column(default=0)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class HypothesisVerdict(str, enum.Enum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    INCONCLUSIVE = "inconclusive"


class Hypothesis(Base):
    """A tested AI Hypothesis (V3 Phase 8): "{SYMBOL} reacts stronger to
    {EVENT_A} than to {EVENT_B}", tested statistically via the Research
    Engine (app/services/hypothesis/evaluation.py) -- accepted/rejected/
    inconclusive is a deterministic magnitude comparison with a minimum
    sample-size gate, never an LLM's judgment call. `result_a`/`result_b`
    store the exact Research Engine outputs the verdict was computed
    from, so every verdict is auditable against its real inputs."""

    __tablename__ = "hypotheses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    statement: Mapped[str] = mapped_column(String(300))
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    event_a: Mapped[str] = mapped_column(String(30))
    event_b: Mapped[str] = mapped_column(String(30))
    verdict: Mapped[HypothesisVerdict] = mapped_column(
        Enum(
            HypothesisVerdict,
            name="hypothesis_verdict",
            values_callable=lambda enum_cls: [e.value for e in enum_cls],
        ),
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text)
    result_a: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    result_b: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class RankingSnapshot(Base):
    """A Ranking Engine read (V3 Phase 9): the Signal Engine's factors
    ranked by real predictive power, measured via StrategyLabEngine's
    walk-forward test rather than a separate ranking computation.
    `rankings` is the full ordered list (factor, historical/current
    importance, confidence, the exact backtest metrics each was computed
    from) so a ranking is always auditable against its real inputs."""

    __tablename__ = "ranking_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    target_symbol: Mapped[str] = mapped_column(String(20), index=True)
    rankings: Mapped[list] = mapped_column(JSON, default=list)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class MarketSnapshot(Base):
    """v4.0 Market Replay -- a single point-in-time consolidation of every
    other engine's already-computed latest read (regime, Global Score
    sub-scores, Consensus, per-agent outputs, Portfolio Advice, macro/crypto
    prices, whale/ETF snapshots, news, the latest BTC probability read, and
    alerts logged since the previous snapshot). Nothing here is a new
    computation except Consensus itself (which has no persistence of its
    own elsewhere) -- every other field is a direct read of a row another
    engine already wrote. Every JSON field is nullable and independently
    optional: a snapshot taken before some engine has ever run just honestly
    carries `None` for that field rather than a fabricated placeholder."""

    __tablename__ = "market_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    regime: Mapped[str | None] = mapped_column(String(30), nullable=True)
    health_score: Mapped[int | None] = mapped_column(nullable=True)
    trend_strength_score: Mapped[int | None] = mapped_column(nullable=True)
    risk_score: Mapped[int | None] = mapped_column(nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(nullable=True)
    consensus: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    agents: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    portfolio_advice: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    macro: Mapped[dict] = mapped_column(JSON, default=dict)
    crypto: Mapped[dict] = mapped_column(JSON, default=dict)
    whale: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    etf: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    news: Mapped[dict] = mapped_column(JSON, default=dict)
    predictions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    alerts: Mapped[list] = mapped_column(JSON, default=list)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class BreakoutEvent(Base):
    """v4.0 Breakout Intelligence -- one row per detected breakout,
    breakdown, false breakout, failed breakdown, retest or liquidity sweep
    against the trailing swing high/low. Scored by how many of (volume,
    ATR-relative move size, rolling VWAP, market regime, OI/funding
    momentum, finer-timeframe confirmation) actually agree; any factor the
    platform has no data for is honestly `None`, never defaulted to False,
    and probability_pct/confidence_pct are computed only over the factors
    actually available (see app.services.common.scoring.weighted_average).
    Rows are only written when a detection actually fires -- there is no
    row for "nothing happening"."""

    __tablename__ = "breakout_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    timeframe: Mapped[str] = mapped_column(String(5), index=True)
    event_type: Mapped[str] = mapped_column(String(30))
    direction: Mapped[str] = mapped_column(String(10))
    level: Mapped[float] = mapped_column(Numeric(24, 8))
    price: Mapped[float] = mapped_column(Numeric(24, 8))
    probability_pct: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    confidence_pct: Mapped[int] = mapped_column()
    risk_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    expected_continuation: Mapped[str] = mapped_column(String(40))
    reasoning: Mapped[str] = mapped_column(Text)
    volume_confirmed: Mapped[bool | None] = mapped_column(nullable=True)
    atr_confirmed: Mapped[bool | None] = mapped_column(nullable=True)
    vwap_confirmed: Mapped[bool | None] = mapped_column(nullable=True)
    regime_confirmed: Mapped[bool | None] = mapped_column(nullable=True)
    oi_funding_confirmed: Mapped[bool | None] = mapped_column(nullable=True)
    multi_timeframe_confirmed: Mapped[bool | None] = mapped_column(nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class CriticalAlert(Base):
    """v5.1 Autonomous Critical Alert System -- a SECOND, independent alert
    layer alongside AlertLog/AlertRule above, not a replacement for either.
    Tracks one live "episode" per (category, symbol-or-direction) so
    escalating severity can EDIT the existing Telegram message instead of
    spamming a new one -- `telegram_message_ids` is `{chat_id: message_id}`
    for every chat the live message was sent to. `active=False` means the
    episode is resolved (either it cooled back down or timed out); the next
    detection for the same `alert_key` starts a fresh row/message rather
    than reopening a stale one. Every detection, notified or not, is also
    logged to the existing AlertLog table (alert_type prefixed
    "critical_shock:") so Market Memory/Watchdog cover this system too --
    this table only owns the escalation/message-editing lifecycle, which
    AlertLog (append-only) has no concept of."""

    __tablename__ = "critical_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    alert_key: Mapped[str] = mapped_column(String(60), index=True)
    category: Mapped[str] = mapped_column(String(30))
    tier: Mapped[str] = mapped_column(String(10))
    symbols: Mapped[list] = mapped_column(JSON, default=list)
    message: Mapped[str] = mapped_column(Text)
    telegram_message_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(default=True, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    first_triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TechnicalAnalysisSnapshot(Base):
    """v5.3 TradingView MCP Integration -- the combined, multi-timeframe AI
    Technical Score for one symbol (app/services/technical/engine.py).
    Deliberately does NOT store raw indicator values -- "never expose raw
    indicator values directly to users, AI Brain must interpret them" --
    only the interpreted score/probabilities/signals a consumer (API,
    Telegram, the technical specialist agent, Smart Alerts) is meant to
    see. `source` is "tradingview" when TradingView MCP answered, "local"
    when this project's own synced OHLCV history did instead."""

    __tablename__ = "technical_analysis_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    source: Mapped[str] = mapped_column(String(20))
    bullish_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    bearish_score: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    trend_strength: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    momentum: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    volatility: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    breakout_probability: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    breakdown_probability: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    active_signals: Mapped[list] = mapped_column(JSON, default=list)
    timeframes_covered: Mapped[list] = mapped_column(JSON, default=list)
    support: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    resistance: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class WatchdogSnapshot(Base):
    """v5.4 Next Generation Market Watchdog -- one row per Watchdog cycle
    (app/services/watchdog/engine.py's WatchdogEngine.run_cycle()),
    persisted so "Current Market Status"/"AI Status" reads are cheap
    (no live agent-orchestrator run per dashboard/Telegram request) and so
    "What Changed" can diff against the previous cycle. Every field here is
    read from another engine's own already-computed output
    (GlobalScoreEngine/RegimeDetector/ScenarioEngine/Consensus/Committee/
    TechnicalAnalysisEngine) -- nothing is recomputed from scratch, matching
    "never duplicate calculations already performed by Replay/Committee/
    Consensus/Scenario/Risk"."""

    __tablename__ = "watchdog_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scan_duration_ms: Mapped[float | None] = mapped_column(Numeric(10, 2), nullable=True)
    regime: Mapped[str | None] = mapped_column(String(30), nullable=True)
    market_health: Mapped[str] = mapped_column(String(20))
    global_score: Mapped[int | None] = mapped_column(nullable=True)
    trend_strength_score: Mapped[int | None] = mapped_column(nullable=True)
    risk_score: Mapped[int | None] = mapped_column(nullable=True)
    confidence_score: Mapped[int | None] = mapped_column(nullable=True)
    liquidity_score: Mapped[int | None] = mapped_column(nullable=True)
    volatility: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    consensus: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    committee_decision: Mapped[str | None] = mapped_column(String(10), nullable=True)
    committee_confidence_pct: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    committee_recommendation: Mapped[str | None] = mapped_column(String(60), nullable=True)
    expected_scenario: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expected_scenario_pct: Mapped[int | None] = mapped_column(nullable=True)
    highest_risk: Mapped[str | None] = mapped_column(Text, nullable=True)
    biggest_opportunity: Mapped[str | None] = mapped_column(Text, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class WatchdogEvent(Base):
    """v5.4 -- automatic change-detection events (Trend Strength Increased/
    Decreased, Market Regime Changed, Committee Changed, Confidence
    Increased/Dropped, Risk Increased/Reduced, Liquidity Shift, Volatility
    Spike), created by comparing consecutive WatchdogSnapshot rows
    (app/services/watchdog/detectors.py). Distinct from AlertLog (Smart
    Alert Engine) and CriticalAlert (v5.1) -- this is the Watchdog hub's own
    "what changed" changelog, not a third alert-broadcast system; only a
    gated subset of these ever reach Telegram (`telegram_sent`)."""

    __tablename__ = "watchdog_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(40), index=True)
    message: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    telegram_sent: Mapped[bool] = mapped_column(default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class ScannerSnapshot(Base):
    """v5.5 Market Scanner -- one row per (symbol, scan cycle), the
    scanner's own lightweight price/volume/sector history for its up-to-
    ~500-symbol universe (app/services/scanner/engine.py). Kept separate
    from AssetPrice/SnapshotBatch (the existing market-data pipeline's
    table) rather than reusing it, since AssetPrice is written every
    `market_data_interval_minutes` for a small, curated symbol set consumed
    by Regime/GlobalScore/etc.; mixing in hundreds of scanner-only symbols
    at a different cadence would bloat that table and its consumers'
    queries for no benefit to them."""

    __tablename__ = "scanner_snapshots"
    __table_args__ = (
        # _history_by_symbol() (app/services/scanner/engine.py) filters every
        # scan cycle on symbol IN (...) AND recorded_at >= since, across up to
        # ~500 symbols and a 30-day lookback -- a composite index lets
        # Postgres satisfy that with one index scan instead of intersecting
        # the two single-column indexes below.
        Index("ix_scanner_snapshots_symbol_recorded_at", "symbol", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    name: Mapped[str] = mapped_column(String(80))
    price: Mapped[float] = mapped_column(Numeric(24, 8))
    change_pct_1h: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    change_pct_24h: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    volume_24h: Mapped[float | None] = mapped_column(Numeric(24, 2), nullable=True)
    market_cap: Mapped[float | None] = mapped_column(Numeric(24, 2), nullable=True)
    market_cap_rank: Mapped[int | None] = mapped_column(nullable=True)
    sector: Mapped[str] = mapped_column(String(30), default="Unclassified")
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )


class ScannerAlert(Base):
    """v5.5 Market Scanner -- one live "episode" per (category, symbol-or-
    sector), mirroring CriticalAlert's (v5.1) exact escalation lifecycle so
    a worsening tier EDITS the existing Telegram message instead of
    spamming a new one. Written by MarketScannerEngine (never sends
    Telegram itself -- see its module docstring); `telegram_message_ids`
    is populated by the separate notifier step
    (app/services/scanner/notifier.py) after a successful send. Every
    detection, notified or not, is also logged to the existing AlertLog
    table (alert_type prefixed "scanner:") so Market Memory/Watchdog/Replay
    cover this system too, exactly like v5.1 -- this table only owns the
    escalation/message-editing lifecycle AlertLog has no concept of."""

    __tablename__ = "scanner_alerts"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    alert_key: Mapped[str] = mapped_column(String(60), index=True)
    category: Mapped[str] = mapped_column(String(30))
    tier: Mapped[str] = mapped_column(String(10))
    symbols: Mapped[list] = mapped_column(JSON, default=list)
    message: Mapped[str] = mapped_column(Text)
    telegram_message_ids: Mapped[dict] = mapped_column(JSON, default=dict)
    active: Mapped[bool] = mapped_column(default=True, index=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    first_triggered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PriceForecastSnapshot(Base):
    """AI Forecast Center -- one row per (symbol, horizon, computed_at)
    forecast (app/services/forecast/engine.py's ForecastEngine). The
    target price, checkpoints and distribution are a deterministic
    statistical model over ProbabilityEngine's own empirical
    `avg_forward_return_pct` and ATR -- never a fabricated or LLM-guessed
    price.

    `reference_timestamp` is the exact history candle this forecast was
    computed from -- lets the grading job (mirrors
    app.services.learning.engine.evaluate_predictions()'s index-by-
    timestamp join) look up what actually happened `horizon` later and
    fill in `realized_price`/`error_pct`/`evaluated_at`, instead of only
    ever guessing from wall-clock `computed_at`. All four stay NULL until
    the grading job has actually found enough elapsed history to grade
    this row -- never a fabricated placeholder. `confidence_tier` is the
    same `classify_conviction()` tier already shown on the live forecast,
    persisted here too so the self-learning history table can show
    Predicted/Actual/Error%/Confidence without re-deriving it.

    `direction_correct`/`confidence_correct` are also filled in by the
    grading job, for the Prediction Accuracy dashboard: `direction_correct`
    compares this row's own `direction` label's sign against the realized
    price's real sign of change from `current_price` -- honestly `None`
    (not fabricated) for a "Neutral" call, since a neutral read has no
    direction to grade. `confidence_correct` compares the real |error_pct|
    against this row's own ATR-derived expected volatility band (the same
    "no better than noise" baseline `price_forecast_quality_multiplier`
    already uses) -- `None` until graded."""

    __tablename__ = "price_forecast_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(20), index=True)
    horizon: Mapped[str] = mapped_column(String(10), index=True)
    current_price: Mapped[float] = mapped_column(Numeric(24, 8))
    target_price: Mapped[float] = mapped_column(Numeric(24, 8))
    expected_change_pct: Mapped[float] = mapped_column(Numeric(10, 4))
    direction: Mapped[str] = mapped_column(String(20))
    probability_pct: Mapped[int] = mapped_column()
    confidence_tier: Mapped[str | None] = mapped_column(String(20), nullable=True)
    checkpoints: Mapped[list] = mapped_column(JSON, default=list)
    distribution: Mapped[list] = mapped_column(JSON, default=list)
    key_levels: Mapped[dict] = mapped_column(JSON, default=dict)
    reference_timestamp: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    # Filled in by the grading job once `horizon` has actually elapsed --
    # always NULL until then.
    realized_price: Mapped[float | None] = mapped_column(Numeric(24, 8), nullable=True)
    error_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    direction_correct: Mapped[bool | None] = mapped_column(nullable=True)
    confidence_correct: Mapped[bool | None] = mapped_column(nullable=True)
    evaluated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # V9: this table was already append-only by construction (always
    # INSERT, never UPDATE-in-place) -- forecast_version makes that
    # lineage explicit: the Nth forecast computed for this (symbol,
    # horizon) pair, never reused or overwritten. regime_at_forecast is the
    # raw MarketRegime.value active when this row was computed (distinct
    # from the presentation-only `regime` label in the API payload),
    # recorded so a later cycle can detect "the regime this forecast was
    # conditioned on has since changed" -- see app/services/forecast/
    # invalidation.py. forecast_status/invalidation_reason/invalidated_at
    # are filled in by check_and_invalidate_forecasts(), independent of
    # (and can fire before) the horizon-elapsed grading job above.
    forecast_version: Mapped[int] = mapped_column(default=1)
    regime_at_forecast: Mapped[str | None] = mapped_column(String(30), nullable=True)
    forecast_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    invalidation_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, index=True
    )
