"""Smart Alert Engine -- runs every delta detector against the two most
recent stored readings of each relevant snapshot, gates each detection by
conviction (Step 5's "only high-confidence signals generate alerts"), logs
every detection (broadcast or not) to AlertLog for Market Memory, and
pushes the ones that clear the gate to Telegram.

A second gate, cooldown, sits after conviction: an alert_type that already
broadcast within `_COOLDOWN_MINUTES` is logged again (so Market Memory's
audit trail stays complete) but not re-sent to Telegram. Without this, a
metric oscillating right around its threshold would re-fire the same alert
every cycle -- the Market Watchdog brief's "does NOT spam" requirement.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import (
    AlertLog,
    Correlation,
    FeatureSnapshot,
    GlobalMarketScore,
    HistoricalEvent,
    HistoricalEventCategory,
    MarketRegimeSnapshot,
)
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.alerts.detectors import (
    detect_correlation_break,
    detect_dxy_reversal,
    detect_etf_milestone,
    detect_fed_event_approaching,
    detect_flash_move,
    detect_funding_shift,
    detect_liquidity_change,
    detect_oi_spike,
    detect_regime_change,
    detect_technical_alignment,
    detect_whale_accumulation,
)
from app.services.analysis.regime import RegimeDetector
from app.services.conviction.engine import classify_conviction
from app.services.etf.engine import ETFIntelligenceEngine
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.signals.engine import SignalEngine
from app.services.technical.engine import TechnicalAnalysisEngine
from app.services.technical.provider import TechnicalAnalysisProvider
from app.services.whales.engine import WhaleIntelligenceEngine
from app.telegram.broadcast import broadcast_text

logger = logging.getLogger(__name__)

_CORRELATION_PAIR = ("BTC", "NASDAQ")
_CORRELATION_WINDOW_DAYS = 30
_FED_EVENT_LOOKAHEAD_DAYS = 7
_VOLATILITY_SYMBOL = "BTC"
_COOLDOWN_MINUTES = 60


def _is_on_cooldown(
    last_broadcast_at: datetime | None, now: datetime, cooldown_minutes: int = _COOLDOWN_MINUTES
) -> bool:
    """Pure function: has this alert_type broadcast too recently to fire
    again? `None` (never broadcast before) is never on cooldown."""
    if last_broadcast_at is None:
        return False
    return now - last_broadcast_at < timedelta(minutes=cooldown_minutes)


async def _last_two(
    session_factory: async_sessionmaker[AsyncSession], model: type, timestamp_column, **filters
) -> tuple[object | None, object | None]:
    query = select(model).order_by(timestamp_column.desc()).limit(2)
    for column, value in filters.items():
        query = query.where(getattr(model, column) == value)
    async with session_factory() as session:
        rows = list(await session.scalars(query))
    curr = rows[0] if rows else None
    prev = rows[1] if len(rows) > 1 else None
    return curr, prev


class AlertEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        global_score_engine: GlobalScoreEngine,
        whale_engine: WhaleIntelligenceEngine,
        etf_engine: ETFIntelligenceEngine,
        market_repository: MarketRepository | None = None,
        technical_engine: TechnicalAnalysisEngine | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._global_score_engine = global_score_engine
        self._whale_engine = whale_engine
        self._etf_engine = etf_engine
        self._market_repository = market_repository
        self._technical_engine = technical_engine

    async def _last_broadcast_at(self, alert_type: str) -> datetime | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(AlertLog.triggered_at)
                .where(AlertLog.alert_type == alert_type, AlertLog.broadcast.is_(True))
                .order_by(AlertLog.triggered_at.desc())
                .limit(1)
            )

    async def _log(self, detection: dict) -> AlertLog:
        conviction = classify_conviction(detection["confidence_pct"])
        broadcast = conviction["alert_eligible"]
        if broadcast:
            last_broadcast_at = await self._last_broadcast_at(detection["alert_type"])
            broadcast = not _is_on_cooldown(last_broadcast_at, datetime.now(UTC))
        row = AlertLog(
            alert_type=detection["alert_type"],
            message=detection["message"],
            conviction_tier=conviction["tier"],
            confidence_pct=detection["confidence_pct"],
            broadcast=broadcast,
            data=detection["data"],
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def _detect_regime(self) -> dict | None:
        curr, prev = await _last_two(
            self._session_factory, MarketRegimeSnapshot, MarketRegimeSnapshot.computed_at
        )
        if curr is None:
            return None
        return detect_regime_change(prev.regime.value if prev else None, curr.regime.value)

    async def _detect_dxy(self) -> dict | None:
        curr, prev = await _last_two(
            self._session_factory, MarketRegimeSnapshot, MarketRegimeSnapshot.computed_at
        )
        if curr is None:
            return None
        prev_change = prev.inputs.get("dxy_change_pct") if prev else None
        curr_change = curr.inputs.get("dxy_change_pct")
        return detect_dxy_reversal(prev_change, curr_change)

    async def _detect_correlation(self) -> dict | None:
        symbol_a, symbol_b = _CORRELATION_PAIR
        curr, prev = await _last_two(
            self._session_factory,
            Correlation,
            Correlation.calculated_at,
            symbol_a=symbol_a,
            symbol_b=symbol_b,
            window_days=_CORRELATION_WINDOW_DAYS,
        )
        if curr is None:
            return None
        return detect_correlation_break(
            symbol_a,
            symbol_b,
            _CORRELATION_WINDOW_DAYS,
            float(prev.correlation) if prev else None,
            float(curr.correlation),
        )

    async def _detect_liquidity(self) -> dict | None:
        curr, prev = await _last_two(
            self._session_factory, GlobalMarketScore, GlobalMarketScore.computed_at
        )
        if curr is None:
            return None
        return detect_liquidity_change(prev.liquidity_score if prev else None, curr.liquidity_score)

    async def _detect_whale(self) -> dict | None:
        snapshot = await self._whale_engine.get_snapshot("BTC")
        return detect_whale_accumulation(snapshot)

    async def _detect_etf(self) -> dict | None:
        prev = await self._etf_engine.get_latest()
        curr = await self._etf_engine.get_flow_proxy()
        return detect_etf_milestone(prev.classification if prev else None, curr)

    async def _detect_flash_move(self) -> dict | None:
        if self._market_repository is None:
            return None
        assets = await self._market_repository.get_latest()
        asset = next((a for a in assets if a.symbol == _VOLATILITY_SYMBOL), None)
        if asset is None:
            return None
        change_pct = float(asset.change_pct_24h) if asset.change_pct_24h is not None else None
        return detect_flash_move(_VOLATILITY_SYMBOL, change_pct)

    async def _feature_snapshots(self) -> tuple[FeatureSnapshot | None, FeatureSnapshot | None]:
        return await _last_two(
            self._session_factory,
            FeatureSnapshot,
            FeatureSnapshot.computed_at,
            symbol=_VOLATILITY_SYMBOL,
        )

    async def _detect_funding(self) -> dict | None:
        curr, prev = await self._feature_snapshots()
        if curr is None:
            return None
        return detect_funding_shift(
            prev.features.get("funding_rate_momentum_pct") if prev else None,
            curr.features.get("funding_rate_momentum_pct"),
        )

    async def _detect_oi(self) -> dict | None:
        curr, prev = await self._feature_snapshots()
        if curr is None:
            return None
        return detect_oi_spike(
            prev.features.get("open_interest_change_pct") if prev else None,
            curr.features.get("open_interest_change_pct"),
        )

    async def _detect_technical_alignment(self) -> dict | None:
        if self._technical_engine is None:
            return None
        result = await self._technical_engine.analyze(_VOLATILITY_SYMBOL)
        if result is None:
            return None
        return detect_technical_alignment(result["high_confidence_alignment"], _VOLATILITY_SYMBOL)

    async def _detect_fed_event(self) -> dict | None:
        now = datetime.now(UTC)
        horizon = now + timedelta(days=_FED_EVENT_LOOKAHEAD_DAYS)
        async with self._session_factory() as session:
            event = await session.scalar(
                select(HistoricalEvent)
                .where(
                    HistoricalEvent.category == HistoricalEventCategory.MACRO_POLICY.value,
                    HistoricalEvent.event_date >= now,
                    HistoricalEvent.event_date <= horizon,
                )
                .order_by(HistoricalEvent.event_date.asc())
                .limit(1)
            )
        if event is None:
            return None
        days_until = (event.event_date - now).days
        return detect_fed_event_approaching(days_until, event.title, _FED_EVENT_LOOKAHEAD_DAYS)

    async def check_and_broadcast(self) -> list[AlertLog]:
        # Persisting a fresh Global Market Score / whale / ETF read here
        # guarantees the "current" side of each delta detector's comparison
        # is up to date, without waiting on a separately scheduled job.
        await self._global_score_engine.compute_and_store()
        await self._whale_engine.compute_and_store("BTC")
        await self._etf_engine.compute_and_store()

        detections = [
            d
            for d in [
                await self._detect_regime(),
                await self._detect_dxy(),
                await self._detect_correlation(),
                await self._detect_liquidity(),
                await self._detect_whale(),
                await self._detect_etf(),
                await self._detect_fed_event(),
                await self._detect_flash_move(),
                await self._detect_funding(),
                await self._detect_oi(),
                await self._detect_technical_alignment(),
            ]
            if d is not None
        ]

        logged = [await self._log(d) for d in detections]

        for row in logged:
            if row.broadcast:
                try:
                    await broadcast_text(f"*ALERT* ({row.conviction_tier})\n\n{row.message}")
                except Exception:
                    logger.warning("Failed to broadcast alert %s", row.alert_type, exc_info=True)

        return logged


def build_alert_engine() -> AlertEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    return AlertEngine(
        session_factory,
        global_score_engine,
        WhaleIntelligenceEngine(session_factory),
        ETFIntelligenceEngine(news_repository, session_factory),
        market_repository,
        TechnicalAnalysisEngine(session_factory, TechnicalAnalysisProvider(session_factory)),
    )
