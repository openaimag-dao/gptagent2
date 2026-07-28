"""Autonomous Critical Alert System (v5.1) -- CriticalAlertEngine.

A SECOND, independent alert layer: the Smart Alert Engine
(app/services/alerts/engine.py) and Configurable Alerts
(app/services/alerts/rules.py) are both untouched by this module. No user
configures anything here -- severity comes entirely from price action
(app.services.shocks.detectors) filtered through a composite quality read
built from signals this platform already computes: RegimeDetector,
GlobalScoreEngine, the 5-agent Consensus/Committee (run once per cycle and
reused for both -- see _cycle_context()), ScenarioEngine, and (best-effort,
BTC/ETH/SOL only) SimilarMarketEngine. Nothing here recomputes any of
those; every read is a `get_latest()`-style call against data another
engine's own scheduled job already maintains, exactly like
MarketReplayEngine and TerminalEngine before it.

Escalation: an ongoing shock "episode" is tracked in the CriticalAlert
table by `alert_key` (e.g. "shock:BTC:down" or "multi_asset_shock:down").
A worsening tier on an active episode EDITS the existing Telegram message
(app.telegram.broadcast.edit_text) instead of sending a new one; a
same-or-lower tier is suppressed entirely (no DB write, no Telegram call)
so nothing spams. Every detection, notified or not, is also logged to the
existing AlertLog table (alert_type prefixed "critical_shock:") so Market
Memory/Watchdog cover this system too -- CriticalAlert only owns the
escalation/message-editing lifecycle AlertLog has no concept of.
"""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import AlertLog, CriticalAlert, CryptoHistory, SentimentSnapshot
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.agents.orchestrator import AgentOrchestrator, build_agent_orchestrator
from app.services.analysis.regime import RegimeDetector
from app.services.committee.engine import convene_committee
from app.services.consensus.engine import ConsensusResult, compute_consensus
from app.services.global_score.engine import GlobalScoreEngine
from app.services.history.schemas import Timeframe
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.reliability.engine import AgentReliabilityEngine
from app.services.scenarios.engine import ScenarioEngine
from app.services.shocks.detectors import (
    MONITORED_SYMBOLS,
    WINDOWS_MINUTES,
    best_window_detection,
    committee_alignment_score,
    compute_realized_volatility,
    consensus_alignment_score,
    decide_alert_action,
    detect_multi_asset_shock,
    gate_severity,
    historical_similarity_score,
    regime_alignment_score,
    score_alert_quality,
    should_notify,
    volatility_score,
    volume_change_score,
)
from app.services.signals.engine import SignalEngine
from app.services.similar_market.engine import SimilarMarketEngine
from app.telegram.formatters import format_critical_alert

logger = logging.getLogger(__name__)

_MAX_WINDOW_MINUTES = max(WINDOWS_MINUTES.values())
_LOOKBACK_BUFFER_MINUTES = 10
_SIMILARITY_SYMBOLS = ("BTC", "ETH", "SOL")


class CriticalAlertEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        market_repository: MarketRepository,
        regime_detector: RegimeDetector,
        global_score_engine: GlobalScoreEngine,
        scenario_engine: ScenarioEngine,
        agent_orchestrator: AgentOrchestrator,
        reliability_engine: AgentReliabilityEngine,
        similar_market_engine: SimilarMarketEngine,
    ) -> None:
        self._session_factory = session_factory
        self._market_repository = market_repository
        self._regime_detector = regime_detector
        self._global_score_engine = global_score_engine
        self._scenario_engine = scenario_engine
        self._agent_orchestrator = agent_orchestrator
        self._reliability_engine = reliability_engine
        self._similar_market_engine = similar_market_engine

    async def _safe_reliability(self) -> dict[str, float] | None:
        try:
            return await self._reliability_engine.evaluate_reliability()
        except Exception:
            return None

    async def _cycle_context(self) -> dict:
        regime_snapshot, global_score, scenario_snapshot = await asyncio.gather(
            self._regime_detector.get_latest(),
            self._global_score_engine.get_latest(),
            self._scenario_engine.get_latest(),
        )
        agent_outputs, reliability = await asyncio.gather(
            self._agent_orchestrator.run_all(),
            self._safe_reliability(),
        )
        consensus: ConsensusResult | None = compute_consensus(agent_outputs, reliability)
        committee = convene_committee(agent_outputs, consensus) if consensus is not None else None
        return {
            "regime": regime_snapshot.regime.value if regime_snapshot is not None else None,
            "trend_strength_score": (
                global_score.trend_strength_score if global_score is not None else None
            ),
            "risk_score": global_score.risk_score if global_score is not None else None,
            "confidence_score": (
                global_score.confidence_score if global_score is not None else None
            ),
            "consensus": consensus,
            "committee": committee,
            "scenarios": scenario_snapshot.scenarios if scenario_snapshot is not None else None,
        }

    async def _window_prices(self, symbol: str) -> tuple[dict[str, float | None], list[float]]:
        now = datetime.now(UTC)
        since = now - timedelta(minutes=_MAX_WINDOW_MINUTES + _LOOKBACK_BUFFER_MINUTES)
        history = await self._market_repository.get_history(symbol, since)
        if not history:
            return {w: None for w in WINDOWS_MINUTES}, []
        prices = [float(row.price) for row in history]
        latest_price = prices[-1]
        changes: dict[str, float | None] = {}
        for window, minutes in WINDOWS_MINUTES.items():
            target = now - timedelta(minutes=minutes)
            earlier_row = min(history, key=lambda r: abs((r.recorded_at - target).total_seconds()))
            earlier_price = float(earlier_row.price)
            changes[window] = (
                (latest_price - earlier_price) / earlier_price * 100 if earlier_price else None
            )
        return changes, prices

    async def _fear_greed_window_prices(self) -> tuple[dict[str, float | None], list[float]]:
        now = datetime.now(UTC)
        since = now - timedelta(minutes=_MAX_WINDOW_MINUTES + _LOOKBACK_BUFFER_MINUTES)
        async with self._session_factory() as session:
            rows = list(
                await session.scalars(
                    select(SentimentSnapshot)
                    .where(
                        SentimentSnapshot.computed_at >= since,
                        SentimentSnapshot.fear_greed_value.is_not(None),
                    )
                    .order_by(SentimentSnapshot.computed_at.asc())
                )
            )
        if not rows:
            return {w: None for w in WINDOWS_MINUTES}, []
        values = [float(row.fear_greed_value) for row in rows]
        latest_value = values[-1]
        changes: dict[str, float | None] = {}
        for window, minutes in WINDOWS_MINUTES.items():
            target = now - timedelta(minutes=minutes)
            earlier_row = min(rows, key=lambda r: abs((r.computed_at - target).total_seconds()))
            # An index, not a %-priced asset -- report the point delta, matching
            # THRESHOLDS["FEAR_GREED"]'s index-point scale.
            changes[window] = latest_value - float(earlier_row.fear_greed_value)
        return changes, values

    async def _volume_change(self, symbol: str, window_minutes: int) -> float | None:
        since = datetime.now(UTC) - timedelta(minutes=window_minutes + _LOOKBACK_BUFFER_MINUTES)
        history = await self._market_repository.get_history(symbol, since)
        volumes = [float(row.volume_24h) for row in history if row.volume_24h is not None]
        if len(volumes) < 2:
            return None
        earlier, latest = volumes[0], volumes[-1]
        return (latest - earlier) / earlier * 100 if earlier else None

    async def _historical_forward_returns(self, symbol: str) -> list[float | None] | None:
        if symbol not in _SIMILARITY_SYMBOLS:
            return None
        try:
            episodes = await self._similar_market_engine.find_similar_periods(
                symbol, CryptoHistory, Timeframe.DAILY
            )
        except Exception:
            logger.warning("Historical similarity lookup failed for %s", symbol, exc_info=True)
            return None
        if not episodes:
            return None
        return [e["forward_returns_pct"].get("1d") for e in episodes]

    def _alignment_components(self, ctx: dict, move_direction: str) -> dict:
        consensus = ctx["consensus"]
        committee = ctx["committee"]
        return {
            "regime_alignment": regime_alignment_score(ctx["regime"], move_direction),
            "trend_strength": ctx["trend_strength_score"],
            "consensus_alignment": (
                consensus_alignment_score(
                    consensus.bullish_pct,
                    consensus.bearish_pct,
                    consensus.agreement_score,
                    move_direction,
                )
                if consensus is not None
                else None
            ),
            "committee_alignment": (
                committee_alignment_score(
                    committee.majority_decision, committee.majority_pct, move_direction
                )
                if committee is not None
                else None
            ),
            "risk_score": ctx["risk_score"],
            "confidence_score": ctx["confidence_score"],
        }

    def _context_summary(self, ctx: dict) -> dict:
        return {
            "regime": ctx["regime"],
            "trend_strength_score": ctx["trend_strength_score"],
            "risk_score": ctx["risk_score"],
            "confidence_score": ctx["confidence_score"],
            "committee": ctx["committee"].to_dict() if ctx["committee"] is not None else None,
            "scenarios": ctx["scenarios"],
        }

    async def _build_single_envelope(
        self,
        symbol: str,
        detection: dict,
        ctx: dict,
        prices: list[float],
        current_value: float | None,
    ) -> dict:
        pct_change = detection["pct_change"]
        direction = "up" if pct_change > 0 else "down"
        move_direction = "bullish" if direction == "up" else "bearish"
        window_minutes = WINDOWS_MINUTES[detection["window"]]

        volume_pct = (
            await self._volume_change(symbol, window_minutes) if symbol != "FEAR_GREED" else None
        )
        realized_vol = compute_realized_volatility(prices)
        forward_returns = await self._historical_forward_returns(symbol)

        components = {
            "volume": volume_change_score(volume_pct),
            "volatility": volatility_score(realized_vol),
            "historical_similarity": (
                historical_similarity_score(forward_returns, move_direction)
                if forward_returns is not None
                else None
            ),
            **self._alignment_components(ctx, move_direction),
        }

        return {
            "alert_key": f"shock:{symbol}:{direction}",
            "category": "price_shock",
            "symbols": [symbol],
            "direction": direction,
            "raw_tier": detection["tier"],
            "readings": [
                {
                    "symbol": symbol,
                    "window": detection["window"],
                    "pct_change": pct_change,
                    "current_value": current_value,
                }
            ],
            "quality_components": components,
            "context": self._context_summary(ctx),
        }

    async def _build_multi_asset_envelope(
        self, multi_asset: dict, ctx: dict, per_symbol_current: dict[str, float | None]
    ) -> dict:
        direction = multi_asset["direction"]
        move_direction = "bullish" if direction == "up" else "bearish"
        moves = multi_asset["moves"]
        primary = next((m["symbol"] for m in moves if m["symbol"] in _SIMILARITY_SYMBOLS), None)
        forward_returns = await self._historical_forward_returns(primary) if primary else None

        components = {
            "volume": None,
            "volatility": None,
            "historical_similarity": (
                historical_similarity_score(forward_returns, move_direction)
                if forward_returns is not None
                else None
            ),
            **self._alignment_components(ctx, move_direction),
        }

        return {
            "alert_key": f"multi_asset_shock:{direction}",
            "category": "multi_asset_shock",
            "symbols": [m["symbol"] for m in moves],
            "direction": direction,
            "raw_tier": multi_asset["tier"],
            "readings": [
                {
                    "symbol": m["symbol"],
                    "window": m["window"],
                    "pct_change": m["pct_change"],
                    "current_value": per_symbol_current.get(m["symbol"]),
                }
                for m in moves
            ],
            "quality_components": components,
            "context": self._context_summary(ctx),
        }

    async def _broadcast_new(self, message: str) -> dict[str, int]:
        # Imported here, not at module scope, to avoid a circular import:
        # app.telegram.handlers imports this module (for the /shocks
        # command), and app.telegram.broadcast imports app.telegram.bot,
        # which imports app.telegram.handlers -- same fix as
        # app.services.alerts.rules.evaluate_all() in Phase 8.
        from app.telegram.broadcast import parse_chat_ids, send_text_to_with_id

        chat_ids = parse_chat_ids(get_settings().telegram_broadcast_chat_ids)
        ids: dict[str, int] = {}
        for chat_id in chat_ids:
            message_id = await send_text_to_with_id(chat_id, message)
            if message_id is not None:
                ids[str(chat_id)] = message_id
        return ids

    async def _edit_existing(self, telegram_message_ids: dict, message: str) -> bool:
        from app.telegram.broadcast import edit_text

        any_ok = False
        for chat_id_str, message_id in telegram_message_ids.items():
            ok = await edit_text(int(chat_id_str), message_id, message)
            any_ok = any_ok or ok
        return any_ok

    async def _log_to_alert_log(
        self, envelope: dict, tier: str, quality_score: float | None, notified: bool
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                AlertLog(
                    alert_type=f"critical_shock:{envelope['category']}",
                    message=(
                        f"{envelope['category']} tier={tier} "
                        f"symbols={','.join(envelope['symbols'])}"
                    ),
                    conviction_tier=tier,
                    confidence_pct=round(quality_score) if quality_score is not None else 0,
                    broadcast=notified,
                    data={
                        "alert_key": envelope["alert_key"],
                        "readings": envelope["readings"],
                        "quality_score": quality_score,
                    },
                )
            )
            await session.commit()

    async def _process_envelope(self, envelope: dict, now: datetime) -> dict:
        quality_score = score_alert_quality(envelope["quality_components"])
        tier = gate_severity(envelope["raw_tier"], quality_score)
        notify_eligible = should_notify(tier)
        message = format_critical_alert(envelope, tier, quality_score)

        async with self._session_factory() as session:
            existing = await session.scalar(
                select(CriticalAlert)
                .where(
                    CriticalAlert.alert_key == envelope["alert_key"],
                    CriticalAlert.active.is_(True),
                )
                .order_by(CriticalAlert.last_updated_at.desc())
                .limit(1)
            )

        action = decide_alert_action(
            existing_active=existing is not None,
            existing_tier=existing.tier if existing is not None else None,
            new_tier=tier,
            now=now,
            last_updated_at=existing.last_updated_at if existing is not None else None,
        )

        if action == "resolve_then_new":
            async with self._session_factory() as session:
                row = await session.get(CriticalAlert, existing.id)
                if row is not None:
                    row.active = False
                    row.resolved_at = now
                await session.commit()
            action = "new"
            existing = None

        telegram_message_ids: dict[str, int] = {}
        notified = False

        if action == "new":
            if notify_eligible:
                telegram_message_ids = await self._broadcast_new(message)
                notified = bool(telegram_message_ids)
            async with self._session_factory() as session:
                session.add(
                    CriticalAlert(
                        alert_key=envelope["alert_key"],
                        category=envelope["category"],
                        tier=tier,
                        symbols=envelope["symbols"],
                        message=message,
                        telegram_message_ids=telegram_message_ids,
                        active=True,
                        data={"quality_score": quality_score, "readings": envelope["readings"]},
                        first_triggered_at=now,
                        last_updated_at=now,
                    )
                )
                await session.commit()
        elif action == "escalate":
            if notify_eligible:
                if existing.telegram_message_ids:
                    notified = await self._edit_existing(existing.telegram_message_ids, message)
                    telegram_message_ids = existing.telegram_message_ids
                else:
                    telegram_message_ids = await self._broadcast_new(message)
                    notified = bool(telegram_message_ids)
            else:
                telegram_message_ids = existing.telegram_message_ids
            async with self._session_factory() as session:
                row = await session.get(CriticalAlert, existing.id)
                if row is not None:
                    row.tier = tier
                    row.message = message
                    row.telegram_message_ids = telegram_message_ids
                    row.last_updated_at = now
                    row.data = {"quality_score": quality_score, "readings": envelope["readings"]}
                await session.commit()
        # action == "suppress": no DB write, no Telegram call -- this is the
        # dedup path that keeps an unchanging/declining reading from spamming.

        await self._log_to_alert_log(envelope, tier, quality_score, notified)

        return {
            "alert_key": envelope["alert_key"],
            "category": envelope["category"],
            "symbols": envelope["symbols"],
            "tier": tier,
            "quality_score": quality_score,
            "action": action,
            "notified": notified,
            "message": message,
        }

    async def run_cycle(self) -> list[dict]:
        ctx = await self._cycle_context()
        now = datetime.now(UTC)

        latest_assets = await self._market_repository.get_latest()
        latest_by_symbol = {a.symbol: float(a.price) for a in latest_assets}

        per_symbol_detections: dict[str, dict | None] = {}
        per_symbol_prices: dict[str, list[float]] = {}
        per_symbol_current: dict[str, float | None] = {}

        for symbol in MONITORED_SYMBOLS:
            if symbol == "FEAR_GREED":
                changes, values = await self._fear_greed_window_prices()
                current = values[-1] if values else None
            else:
                changes, values = await self._window_prices(symbol)
                current = latest_by_symbol.get(symbol, values[-1] if values else None)
            per_symbol_prices[symbol] = values
            per_symbol_current[symbol] = current
            per_symbol_detections[symbol] = best_window_detection(symbol, changes)

        multi_asset = detect_multi_asset_shock(per_symbol_detections)

        processed: list[dict] = []
        handled_symbols: set[str] = set()

        if multi_asset is not None:
            handled_symbols = {m["symbol"] for m in multi_asset["moves"]}
            envelope = await self._build_multi_asset_envelope(multi_asset, ctx, per_symbol_current)
            processed.append(await self._process_envelope(envelope, now))

        for symbol, detection in per_symbol_detections.items():
            if detection is None or symbol in handled_symbols:
                continue
            envelope = await self._build_single_envelope(
                symbol, detection, ctx, per_symbol_prices[symbol], per_symbol_current[symbol]
            )
            processed.append(await self._process_envelope(envelope, now))

        return processed

    async def list_active(self) -> list[CriticalAlert]:
        async with self._session_factory() as session:
            return list(
                await session.scalars(
                    select(CriticalAlert)
                    .where(CriticalAlert.active.is_(True))
                    .order_by(CriticalAlert.last_updated_at.desc())
                )
            )

    async def list_history(self, limit: int = 20) -> list[CriticalAlert]:
        async with self._session_factory() as session:
            return list(
                await session.scalars(
                    select(CriticalAlert)
                    .order_by(CriticalAlert.last_updated_at.desc())
                    .limit(limit)
                )
            )


def build_critical_alert_engine() -> CriticalAlertEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    return CriticalAlertEngine(
        session_factory,
        market_repository,
        regime_detector,
        global_score_engine,
        ScenarioEngine(session_factory, global_score_engine),
        build_agent_orchestrator(),
        AgentReliabilityEngine(session_factory),
        SimilarMarketEngine(session_factory),
    )
