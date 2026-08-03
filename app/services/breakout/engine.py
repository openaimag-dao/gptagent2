"""Breakout Intelligence Engine -- scans a symbol's stored OHLCV history for
breakouts, breakdowns, false breakouts, failed breakdowns, retests and
liquidity sweeps against the trailing swing high/low (app.services.
breakout.detectors.detect_breakout_event), and scores each detection by
how many of six independent signals actually agree. Extends rather than
recomputes: ATR/volume are read straight off the already-persisted
history row (app.services.history.repository.fill_missing_indicators),
regime comes from RegimeDetector.get_latest(), and OI/funding momentum
comes from FeatureEngine.get_latest() -- the same sources
PortfolioAdvisorEngine and MarketReplayEngine already read.
"""

import asyncio
import logging
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import BreakoutEvent, MarketRegimeType
from app.services.analysis.regime import RegimeDetector
from app.services.breakout.detectors import (
    DEFAULT_LOOKBACK,
    DEFAULT_RECENT_WINDOW,
    compute_rolling_vwap,
    detect_breakout_event,
    score_breakout_event,
)
from app.services.features.engine import FeatureEngine
from app.services.history.registry import HistorySymbolConfig, find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe

logger = logging.getLogger(__name__)

_LOOKBACK = DEFAULT_LOOKBACK
_MIN_CANDLES = DEFAULT_LOOKBACK + DEFAULT_RECENT_WINDOW + 1
_VOLUME_CONFIRM_RATIO = 1.2
_ATR_CONFIRM_MULTIPLE = 0.5

_BULLISH_REGIMES = frozenset(
    {
        MarketRegimeType.RISK_ON,
        MarketRegimeType.LIQUIDITY_EXPANSION,
        MarketRegimeType.BULL,
        MarketRegimeType.ACCUMULATION,
        MarketRegimeType.RECOVERY,
        MarketRegimeType.STRONG_BULL,
        MarketRegimeType.ALTSEASON,
    }
)
_BEARISH_REGIMES = frozenset(
    {
        MarketRegimeType.RISK_OFF,
        MarketRegimeType.LIQUIDITY_CONTRACTION,
        MarketRegimeType.FLIGHT_TO_SAFETY,
        MarketRegimeType.BEAR,
        MarketRegimeType.DISTRIBUTION,
        MarketRegimeType.CAPITULATION,
        MarketRegimeType.BULL_WEAKENING,
    }
)

# Which finer timeframe confirms a detection on a given timeframe -- 1h has
# no finer series stored, so multi-timeframe confirmation is honestly
# unavailable there.
_FINER_TIMEFRAME: dict[Timeframe, Timeframe] = {
    Timeframe.DAILY: Timeframe.FOUR_HOUR,
    Timeframe.FOUR_HOUR: Timeframe.ONE_HOUR,
}


class BreakoutEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        regime_detector: RegimeDetector,
        feature_engine: FeatureEngine,
    ) -> None:
        self._session_factory = session_factory
        self._regime_detector = regime_detector
        self._feature_engine = feature_engine

    async def _confirm_multi_timeframe(
        self, config: HistorySymbolConfig, timeframe: Timeframe, direction: str
    ) -> bool | None:
        finer = _FINER_TIMEFRAME.get(timeframe)
        if finer is None or finer not in config.timeframes:
            return None
        rows = await get_series(self._session_factory, config.model, config.symbol, finer)
        if len(rows) < _MIN_CANDLES:
            return None
        event = detect_breakout_event(
            [float(r.high) for r in rows],
            [float(r.low) for r in rows],
            [float(r.close) for r in rows],
            lookback=_LOOKBACK,
        )
        if event is None:
            return None
        return event["direction"] == direction

    async def _confirm_regime(self, direction: str) -> bool | None:
        snapshot = await self._regime_detector.get_latest()
        if snapshot is None:
            return None
        if snapshot.regime in _BULLISH_REGIMES:
            return direction == "bullish"
        if snapshot.regime in _BEARISH_REGIMES:
            return direction == "bearish"
        return None

    async def _confirm_oi_funding(self, symbol: str, direction: str) -> bool | None:
        snapshot = await self._feature_engine.get_latest(symbol)
        if snapshot is None:
            return None
        funding = snapshot.features.get("funding_rate_momentum_pct")
        oi = snapshot.features.get("open_interest_change_pct")
        signals = [v for v in (funding, oi) if v is not None]
        if not signals:
            return None
        net = sum(signals)
        if net == 0:
            return None
        return (net > 0) == (direction == "bullish")

    async def compute_and_store(
        self, symbol: str, model: type, timeframe: Timeframe = Timeframe.DAILY
    ) -> BreakoutEvent | None:
        rows = await get_series(self._session_factory, model, symbol, timeframe)
        if len(rows) < _MIN_CANDLES:
            return None

        highs = [float(r.high) for r in rows]
        lows = [float(r.low) for r in rows]
        closes = [float(r.close) for r in rows]
        volumes: list[float | None] = [
            float(r.volume) if r.volume is not None else None for r in rows
        ]

        event = detect_breakout_event(highs, lows, closes, lookback=_LOOKBACK)
        if event is None:
            return None

        atr = float(rows[-1].atr) if rows[-1].atr is not None else None

        volume_confirmed: bool | None = None
        prior_volumes = [v for v in volumes[:-1][-_LOOKBACK:] if v is not None]
        if prior_volumes and volumes[-1] is not None:
            avg_volume = sum(prior_volumes) / len(prior_volumes)
            if avg_volume > 0:
                volume_confirmed = (volumes[-1] / avg_volume) >= _VOLUME_CONFIRM_RATIO

        atr_confirmed: bool | None = None
        if atr is not None and atr > 0:
            atr_confirmed = abs(event["price"] - event["level"]) / atr >= _ATR_CONFIRM_MULTIPLE

        vwap = compute_rolling_vwap(highs, lows, closes, volumes, window=_LOOKBACK)
        vwap_confirmed: bool | None = None
        if vwap is not None:
            vwap_confirmed = (
                event["price"] > vwap if event["direction"] == "bullish" else event["price"] < vwap
            )

        config = find_symbol_config(symbol)

        async def _multi_timeframe() -> bool | None:
            if config is None:
                return None
            return await self._confirm_multi_timeframe(config, timeframe, event["direction"])

        # Three independent confirmations (regime detector, OI/funding feature
        # snapshot, multi-timeframe history) -- gathered rather than sequential.
        regime_confirmed, oi_funding_confirmed, multi_timeframe_confirmed = await asyncio.gather(
            self._confirm_regime(event["direction"]),
            self._confirm_oi_funding(symbol, event["direction"]),
            _multi_timeframe(),
        )

        confirmations = {
            "volume": volume_confirmed,
            "atr": atr_confirmed,
            "vwap": vwap_confirmed,
            "regime": regime_confirmed,
            "oi_funding": oi_funding_confirmed,
            "multi_timeframe": multi_timeframe_confirmed,
        }
        scored = score_breakout_event(
            event["event_type"],
            event["direction"],
            event["price"],
            event["level"],
            atr,
            confirmations,
        )

        row = BreakoutEvent(
            symbol=symbol.upper(),
            timeframe=timeframe.value,
            event_type=event["event_type"],
            direction=event["direction"],
            level=event["level"],
            price=event["price"],
            probability_pct=scored["probability_pct"],
            confidence_pct=scored["confidence_pct"],
            risk_score=scored["risk_score"],
            expected_continuation=scored["expected_continuation"],
            reasoning=scored["reasoning"],
            volume_confirmed=volume_confirmed,
            atr_confirmed=atr_confirmed,
            vwap_confirmed=vwap_confirmed,
            regime_confirmed=regime_confirmed,
            oi_funding_confirmed=oi_funding_confirmed,
            multi_timeframe_confirmed=multi_timeframe_confirmed,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def get_latest(
        self, symbol: str, timeframe: Timeframe = Timeframe.DAILY
    ) -> BreakoutEvent | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(BreakoutEvent)
                .where(
                    BreakoutEvent.symbol == symbol.upper(),
                    BreakoutEvent.timeframe == timeframe.value,
                )
                .order_by(BreakoutEvent.computed_at.desc())
                .limit(1)
            )

    async def get_recent(
        self, symbol: str, timeframe: Timeframe = Timeframe.DAILY, limit: int = 10
    ) -> list[BreakoutEvent]:
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(BreakoutEvent)
                .where(
                    BreakoutEvent.symbol == symbol.upper(),
                    BreakoutEvent.timeframe == timeframe.value,
                )
                .order_by(BreakoutEvent.computed_at.desc())
                .limit(limit)
            )
            return list(rows)

    async def get_latest_across(
        self, symbols: Sequence[str], timeframe: Timeframe = Timeframe.DAILY
    ) -> list[BreakoutEvent]:
        """Most recent detection per symbol across a symbol universe -- one
        query, then keep the first (most recent) row per symbol in Python.
        Reads what compute_breakout_job already persisted; does not trigger
        a new computation, so this stays cheap enough for a dashboard load."""
        upper_symbols = [s.upper() for s in symbols]
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(BreakoutEvent)
                .where(
                    BreakoutEvent.symbol.in_(upper_symbols),
                    BreakoutEvent.timeframe == timeframe.value,
                )
                .order_by(BreakoutEvent.computed_at.desc())
            )
            latest_by_symbol: dict[str, BreakoutEvent] = {}
            for row in rows:
                latest_by_symbol.setdefault(row.symbol, row)
            return list(latest_by_symbol.values())
