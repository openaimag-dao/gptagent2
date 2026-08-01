"""TechnicalAnalysisEngine -- the top of the Provider Layer -> Event Bus ->
Existing Engines chain: composes TechnicalAnalysisProvider (TradingView
MCP or local fallback), scoring.py (AI Technical Score, multi-timeframe
combination) and signals.py (event detection) into one persisted,
AI-interpreted reading per symbol. Never returns raw indicator values --
only the interpreted score/probabilities/signals -- matching "never expose
raw indicator values directly to users" from the mission.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import TechnicalAnalysisSnapshot
from app.database.session import get_session_factory
from app.services.technical.provider import TechnicalAnalysisProvider
from app.services.technical.scoring import (
    combine_multi_timeframe,
    compute_breakout_breakdown_probability,
    score_timeframe,
)
from app.services.technical.signals import (
    detect_golden_death_cross,
    detect_high_confidence_alignment,
    detect_macd_crossover,
    detect_rsi_signals,
    detect_support_resistance_events,
    detect_technical_bias,
    detect_trend_change,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEFRAMES: tuple[str, ...] = ("1h", "4h", "1d", "1w")


class TechnicalAnalysisEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        provider: TechnicalAnalysisProvider,
    ) -> None:
        self._session_factory = session_factory
        self._provider = provider

    async def _previous_snapshot(self, symbol: str) -> TechnicalAnalysisSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(TechnicalAnalysisSnapshot)
                .where(TechnicalAnalysisSnapshot.symbol == symbol)
                .order_by(TechnicalAnalysisSnapshot.computed_at.desc())
                .limit(1)
            )

    async def analyze(
        self, symbol: str, timeframe_labels: tuple[str, ...] = DEFAULT_TIMEFRAMES
    ) -> dict | None:
        symbol = symbol.upper()
        readings = await self._provider.get_multi_timeframe(symbol, timeframe_labels)
        per_timeframe_scores = {
            label: score_timeframe(reading) for label, reading in readings.items()
        }
        combined = combine_multi_timeframe(per_timeframe_scores)
        if combined is None:
            return None

        daily_reading = readings.get("1d")
        breakout, breakdown = compute_breakout_breakdown_probability(daily_reading)

        current_daily, previous_daily = await self._provider.get_daily_pair(symbol)
        macd_event = detect_macd_crossover(previous_daily, current_daily)
        cross_event = detect_golden_death_cross(previous_daily, current_daily)
        sr_events = detect_support_resistance_events(current_daily)
        rsi_events = detect_rsi_signals(current_daily)

        previous_snapshot = await self._previous_snapshot(symbol)
        previous_combined = (
            {"trend_strength": float(previous_snapshot.trend_strength)}
            if previous_snapshot is not None and previous_snapshot.trend_strength is not None
            else None
        )
        trend_event = detect_trend_change(previous_combined, combined)
        bias_event = detect_technical_bias(combined)
        alignment = detect_high_confidence_alignment(current_daily, macd_event, sr_events)

        active_signals = [
            e for e in (cross_event, macd_event, trend_event, bias_event) if e is not None
        ]
        active_signals.extend(rsi_events)
        active_signals.extend(sr_events)

        source = "unavailable"
        for reading in readings.values():
            if reading is not None:
                source = reading.source
                break

        result = {
            "symbol": symbol,
            "source": source,
            "bullish_score": combined["bullish_score"],
            "bearish_score": combined["bearish_score"],
            "trend_strength": combined["trend_strength"],
            "momentum": combined["momentum"],
            "volatility": combined["volatility"],
            "confidence": combined["confidence"],
            "timeframes_covered": combined["timeframes_covered"],
            "timeframes_requested": combined["timeframes_requested"],
            "breakout_probability": breakout,
            "breakdown_probability": breakdown,
            "support": daily_reading.support if daily_reading is not None else None,
            "resistance": daily_reading.resistance if daily_reading is not None else None,
            "active_signals": active_signals,
            "high_confidence_alignment": alignment,
            "computed_at": datetime.now(UTC).isoformat(),
        }

        await self._persist(result)
        return result

    async def _persist(self, result: dict) -> None:
        async with self._session_factory() as session:
            session.add(
                TechnicalAnalysisSnapshot(
                    symbol=result["symbol"],
                    source=result["source"],
                    bullish_score=result["bullish_score"],
                    bearish_score=result["bearish_score"],
                    trend_strength=result["trend_strength"],
                    momentum=result["momentum"],
                    volatility=result["volatility"],
                    breakout_probability=result["breakout_probability"],
                    breakdown_probability=result["breakdown_probability"],
                    confidence=result["confidence"],
                    active_signals=result["active_signals"],
                    timeframes_covered=result["timeframes_covered"],
                    support=result["support"],
                    resistance=result["resistance"],
                )
            )
            await session.commit()

    async def get_latest(self, symbol: str) -> TechnicalAnalysisSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(TechnicalAnalysisSnapshot)
                .where(TechnicalAnalysisSnapshot.symbol == symbol.upper())
                .order_by(TechnicalAnalysisSnapshot.computed_at.desc())
                .limit(1)
            )


def build_technical_analysis_engine() -> TechnicalAnalysisEngine:
    session_factory = get_session_factory()
    return TechnicalAnalysisEngine(session_factory, TechnicalAnalysisProvider(session_factory))
