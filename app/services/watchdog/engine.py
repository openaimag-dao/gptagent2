"""WatchdogEngine -- the v5.4 Next Generation Market Watchdog. Upgrades the
existing Watchdog (AlertLog/MemoryEngine "alerts" category, kept exactly as
is -- see get_dashboard()) into a real-time Market Status Dashboard by
composing already-computed outputs from GlobalScoreEngine, RegimeDetector,
ScenarioEngine, MarketReplayEngine, TechnicalAnalysisEngine,
OnChainIntelligenceEngine, WhaleIntelligenceEngine and the Consensus/
Committee pure functions -- the exact "run the agent orchestrator once per
cycle, reuse the result for everything" pattern CriticalAlertEngine
(app/services/shocks/engine.py) established for v5.1. Nothing here
recomputes another engine's own number; every read-only method below is a
`get_latest()`-style call or a persisted WatchdogSnapshot read.

Expensive work (one agent-orchestrator run, consensus, committee) happens
ONLY inside run_cycle(), on its own scheduler cadence
(compute_watchdog_snapshot_job) -- every other method here is a cheap read
of the resulting persisted WatchdogSnapshot, so a dashboard/Telegram
request never triggers a fresh agent run ("cache expensive calculations").
"""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import WatchdogEvent, WatchdogSnapshot
from app.services.agents.orchestrator import AgentOrchestrator
from app.services.analysis.regime import RegimeDetector
from app.services.committee.engine import convene_committee
from app.services.common.ai_insight import build_ai_insight
from app.services.consensus.engine import compute_consensus
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository
from app.services.memory.engine import MemoryEngine
from app.services.onchain.engine import OnChainIntelligenceEngine
from app.services.reliability.engine import AgentReliabilityEngine
from app.services.replay.engine import MarketReplayEngine
from app.services.scenarios.engine import ScenarioEngine, scenario_extremes
from app.services.shocks.detectors import compute_window_changes, regime_direction_bucket
from app.services.technical.engine import TechnicalAnalysisEngine
from app.services.watchdog.detectors import (
    classify_bias,
    classify_market_health,
    detect_all_changes,
    freshness_status,
    is_telegram_eligible,
)
from app.services.whales.engine import WhaleIntelligenceEngine

logger = logging.getLogger(__name__)

WATCHDOG_CRYPTO_SYMBOLS: tuple[str, ...] = ("BTC", "ETH", "SOL", "BNB", "LINK", "ADA", "AVAX")
WATCHDOG_MACRO_SYMBOLS: tuple[str, ...] = (
    "DXY",
    "VIX",
    "GOLD",
    "OIL",
    "US10Y",
    "US02Y",
    "NASDAQ",
    "SPX",
    "DJI",
    "RUT",
)
_MACRO_LABELS: dict[str, str] = {
    "DXY": "DXY",
    "VIX": "VIX",
    "GOLD": "Gold",
    "OIL": "Oil",
    "US10Y": "US10Y",
    "US02Y": "US02Y",
    "NASDAQ": "Nasdaq",
    "SPX": "S&P 500",
    "DJI": "Dow Jones",
    "RUT": "Russell 2000",
}
# A documented directional heuristic (which way this macro symbol typically
# pressures crypto), not a measured correlation -- same spirit as
# global_score's own static _REGIME_RISK_SPLIT table.
_MACRO_CRYPTO_IMPACT: dict[str, tuple[str, str]] = {
    "DXY": ("up", "bearish"),
    "VIX": ("up", "bearish"),
    "US10Y": ("up", "bearish"),
    "US02Y": ("up", "bearish"),
    "OIL": ("up", "mixed"),
    "GOLD": ("up", "mixed"),
    "NASDAQ": ("up", "bullish"),
    "SPX": ("up", "bullish"),
    "DJI": ("up", "bullish"),
    "RUT": ("up", "bullish"),
}

_WINDOWS: dict[str, int] = {"15m": 15, "1h": 60, "24h": 1440}
_MAX_WINDOW_MINUTES = max(_WINDOWS.values())
_LOOKBACK_BUFFER_MINUTES = 10
_TELEGRAM_COOLDOWN_MINUTES = 60
_ALERT_HISTORY_LIMIT = 15


def _trend_label(pct_change: float | None) -> str | None:
    if pct_change is None:
        return None
    if pct_change > 0.5:
        return "Up"
    if pct_change < -0.5:
        return "Down"
    return "Flat"


def macro_impact_on_crypto(symbol: str, pct_change: float | None) -> str | None:
    """A documented directional heuristic label, not a fabricated
    measurement -- see _MACRO_CRYPTO_IMPACT's module docstring note."""
    if pct_change is None:
        return None
    rule = _MACRO_CRYPTO_IMPACT.get(symbol)
    if rule is None:
        return None
    up_direction, up_impact = rule
    if pct_change > 0.1:
        return up_impact if up_direction == "up" else _invert(up_impact)
    if pct_change < -0.1:
        return _invert(up_impact) if up_direction == "up" else up_impact
    return "neutral"


def _invert(impact: str) -> str:
    return {"bullish": "bearish", "bearish": "bullish", "mixed": "mixed"}.get(impact, impact)


def _is_on_cooldown(last_sent_at: datetime | None, now: datetime, cooldown_minutes: int) -> bool:
    if last_sent_at is None:
        return False
    return (now - last_sent_at).total_seconds() < cooldown_minutes * 60


def build_watchdog_snapshot_insight(row: WatchdogSnapshot | None) -> dict:
    """v12.0 "Unified Intelligence" -- composes the latest WatchdogSnapshot's
    already-persisted regime/scores/consensus/committee/scenario fields into
    the shared AI Insight shape (app.services.common.ai_insight), so other
    screens that already read a WatchdogSnapshot (Scanner's
    get_market_context(), Watchdog's own get_ai_status()) can offer the same
    "what/why/opportunity/risk/scenario" summary Replay already has, with no
    new query and no new engine. `why`/`supporting_evidence`/
    `historical_similarity`/`what_to_watch_next` are honestly left unset --
    WatchdogSnapshot doesn't persist per-agent evidence or a similarity
    search (unlike MarketSnapshot), so fabricating them here would violate
    "never fabricate market data"."""
    if row is None:
        return build_ai_insight()
    regime_label = (row.regime or "unknown").replace("_", " ").title()
    if row.risk_score is not None and row.confidence_score is not None:
        current_status = (
            f"{regime_label} regime -- {row.market_health}, "
            f"risk {row.risk_score}/100, confidence {row.confidence_score}/100."
        )
    else:
        current_status = f"{regime_label} regime -- {row.market_health}."
    consensus_summary = None
    if row.consensus:
        c = row.consensus
        consensus_summary = (
            f"Bullish {c['bullish_pct']}% / Bearish {c['bearish_pct']}% / "
            f"Neutral {c['neutral_pct']}% (agreement {c['agreement_score']}%)"
        )
    committee_opinion = None
    if row.committee_decision is not None:
        majority_str = (
            f" ({row.committee_confidence_pct}%)"
            if row.committee_confidence_pct is not None
            else ""
        )
        committee_opinion = f"{row.committee_decision}{majority_str}"
    expected_scenario = None
    if row.expected_scenario:
        pct_str = (
            f" ({row.expected_scenario_pct}%)" if row.expected_scenario_pct is not None else ""
        )
        expected_scenario = f"{row.expected_scenario}{pct_str}"
    return build_ai_insight(
        current_status=current_status,
        ai_conclusion=row.committee_recommendation,
        committee_opinion=committee_opinion,
        consensus=consensus_summary,
        main_opportunity=row.biggest_opportunity,
        main_risk=row.highest_risk,
        expected_scenario=expected_scenario,
        confidence=row.confidence_score,
    )


class WatchdogEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        market_repository: MarketRepository,
        global_score_engine: GlobalScoreEngine,
        regime_detector: RegimeDetector,
        scenario_engine: ScenarioEngine,
        replay_engine: MarketReplayEngine,
        onchain_engine: OnChainIntelligenceEngine,
        whale_engine: WhaleIntelligenceEngine,
        technical_engine: TechnicalAnalysisEngine,
        agent_orchestrator: AgentOrchestrator,
        reliability_engine: AgentReliabilityEngine | None = None,
        redis_client: Redis | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._market_repository = market_repository
        self._global_score_engine = global_score_engine
        self._regime_detector = regime_detector
        self._scenario_engine = scenario_engine
        self._replay_engine = replay_engine
        self._onchain_engine = onchain_engine
        self._whale_engine = whale_engine
        self._technical_engine = technical_engine
        self._agent_orchestrator = agent_orchestrator
        self._reliability_engine = reliability_engine
        self._redis = redis_client

    # ---------------------------------------------------------------- reads

    async def get_latest_snapshot(self) -> WatchdogSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(WatchdogSnapshot).order_by(WatchdogSnapshot.computed_at.desc()).limit(1)
            )

    async def _last_two_snapshots(self) -> tuple[WatchdogSnapshot | None, WatchdogSnapshot | None]:
        async with self._session_factory() as session:
            rows = list(
                await session.scalars(
                    select(WatchdogSnapshot).order_by(WatchdogSnapshot.computed_at.desc()).limit(2)
                )
            )
        curr = rows[0] if rows else None
        prev = rows[1] if len(rows) > 1 else None
        return curr, prev

    async def get_current_status(self) -> dict:
        settings = get_settings()
        now = datetime.now(UTC)
        snapshot = await self.get_latest_snapshot()
        replay_snapshot = await self._replay_engine.get_latest()

        return {
            "current_time": now.isoformat(),
            "last_update": snapshot.computed_at.isoformat() if snapshot is not None else None,
            "scan_duration_ms": (
                float(snapshot.scan_duration_ms)
                if snapshot is not None and snapshot.scan_duration_ms is not None
                else None
            ),
            "market_health": snapshot.market_health if snapshot is not None else "Unknown",
            "brain_status": "ok" if snapshot is not None else "unavailable",
            "replay_status": freshness_status(
                replay_snapshot.computed_at if replay_snapshot is not None else None,
                settings.replay_interval_minutes * 60 * 3,
                now,
            ),
            "committee_status": (
                "ok"
                if snapshot is not None and snapshot.committee_decision is not None
                else "unavailable"
            ),
            "consensus_status": (
                "ok" if snapshot is not None and snapshot.consensus is not None else "unavailable"
            ),
        }

    async def get_market_overview(self) -> dict:
        regime_snapshot, global_score, technical_btc = await asyncio.gather(
            self._regime_detector.get_latest(),
            self._global_score_engine.get_latest(),
            self._technical_engine.get_latest("BTC"),
        )
        regime_value = regime_snapshot.regime.value if regime_snapshot is not None else None
        return {
            "regime": regime_value,
            "trend": (regime_direction_bucket(regime_value).capitalize() if regime_value else None),
            "trend_strength": global_score.trend_strength_score if global_score else None,
            "momentum": (
                float(technical_btc.momentum)
                if technical_btc is not None and technical_btc.momentum is not None
                else None
            ),
            "volatility": (
                float(technical_btc.volatility)
                if technical_btc is not None and technical_btc.volatility is not None
                else None
            ),
            "confidence": global_score.confidence_score if global_score else None,
            "risk_score": global_score.risk_score if global_score else None,
            "liquidity_score": global_score.liquidity_score if global_score else None,
            "market_intelligence_score": global_score.global_score if global_score else None,
        }

    async def _window_changes(self, symbol: str, now: datetime) -> dict[str, float | None]:
        since = now - timedelta(minutes=_MAX_WINDOW_MINUTES + _LOOKBACK_BUFFER_MINUTES)
        history = await self._market_repository.get_history(symbol, since)
        return compute_window_changes(history, now, _WINDOWS)

    async def get_crypto_overview(self) -> list[dict]:
        now = datetime.now(UTC)
        assets = await self._market_repository.get_latest()
        by_symbol = {a.symbol: a for a in assets}

        rows: list[dict] = []
        for symbol in WATCHDOG_CRYPTO_SYMBOLS:
            asset = by_symbol.get(symbol)
            if asset is None:
                rows.append({"symbol": symbol, "available": False})
                continue
            changes = await self._window_changes(symbol, now)
            technical = await self._technical_engine.get_latest(symbol)
            change_pct_24h = (
                float(asset.change_pct_24h) if asset.change_pct_24h is not None else changes["24h"]
            )
            rows.append(
                {
                    "symbol": symbol,
                    "available": True,
                    "price": float(asset.price),
                    "change_pct_24h": change_pct_24h,
                    "change_pct_1h": changes["1h"],
                    "change_pct_15m": changes["15m"],
                    "trend": _trend_label(change_pct_24h),
                    "volume_24h": float(asset.volume_24h) if asset.volume_24h is not None else None,
                    "momentum": (
                        float(technical.momentum)
                        if technical is not None and technical.momentum is not None
                        else None
                    ),
                    "ai_bias": (
                        classify_bias(technical.bullish_score, technical.bearish_score)
                        if technical is not None
                        else None
                    ),
                }
            )
        return rows

    async def get_macro_overview(self) -> list[dict]:
        assets = await self._market_repository.get_latest()
        by_symbol = {a.symbol: a for a in assets}

        rows: list[dict] = []
        for symbol in WATCHDOG_MACRO_SYMBOLS:
            asset = by_symbol.get(symbol)
            if asset is None:
                rows.append({"symbol": symbol, "name": _MACRO_LABELS[symbol], "available": False})
                continue
            daily_pct = float(asset.change_pct_24h) if asset.change_pct_24h is not None else None
            rows.append(
                {
                    "symbol": symbol,
                    "name": _MACRO_LABELS[symbol],
                    "available": True,
                    "price": float(asset.price),
                    "direction": _trend_label(daily_pct),
                    "daily_pct": daily_pct,
                    "trend": _trend_label(daily_pct),
                    "impact_on_crypto": macro_impact_on_crypto(symbol, daily_pct),
                }
            )
        return rows

    async def get_onchain_overview(self) -> dict:
        whale_snapshot, onchain_snapshot = await asyncio.gather(
            self._whale_engine.get_snapshot("BTC"),
            self._onchain_engine.get_snapshot("BTC"),
        )
        metrics = onchain_snapshot.get("metrics", {})
        return {
            "whales": whale_snapshot,
            "funding": whale_snapshot.get("funding_rate")
            if whale_snapshot.get("available")
            else None,
            "open_interest": (
                whale_snapshot.get("open_interest") if whale_snapshot.get("available") else None
            ),
            "exchange_flows": metrics.get("exchange_netflow"),
            "stablecoin_flow": metrics.get("stablecoin_supply"),
            "tvl": metrics.get("tvl"),
            "available": bool(whale_snapshot.get("available")),
            "reason": onchain_snapshot.get("reason"),
        }

    async def get_ai_status(self) -> dict:
        snapshot = await self.get_latest_snapshot()
        if snapshot is None:
            return {
                "committee_opinion": None,
                "consensus": None,
                "prediction_confidence": None,
                "expected_scenario": None,
                "highest_risk": None,
                "biggest_opportunity": None,
                "computed_at": None,
            }
        return {
            "committee_opinion": snapshot.committee_recommendation,
            "consensus": snapshot.consensus,
            "prediction_confidence": (
                float(snapshot.committee_confidence_pct)
                if snapshot.committee_confidence_pct is not None
                else None
            ),
            "expected_scenario": snapshot.expected_scenario,
            "expected_scenario_pct": snapshot.expected_scenario_pct,
            "highest_risk": snapshot.highest_risk,
            "biggest_opportunity": snapshot.biggest_opportunity,
            "computed_at": snapshot.computed_at.isoformat(),
        }

    async def get_what_changed(self) -> dict:
        curr, prev = await self._last_two_snapshots()
        if curr is None:
            return {"available": False, "fields": [], "events": []}

        def _row_dict(row: WatchdogSnapshot | None) -> dict | None:
            if row is None:
                return None
            return {
                "regime": row.regime,
                "trend_strength_score": row.trend_strength_score,
                "confidence_score": row.confidence_score,
                "risk_score": row.risk_score,
                "liquidity_score": row.liquidity_score,
                "volatility": float(row.volatility) if row.volatility is not None else None,
                "committee_decision": row.committee_decision,
            }

        curr_dict = _row_dict(curr)
        prev_dict = _row_dict(prev)
        events = detect_all_changes(prev_dict, curr_dict)

        fields = []
        if prev is not None:
            field_specs = (
                ("Regime", prev.regime, curr.regime),
                ("Trend Strength", prev.trend_strength_score, curr.trend_strength_score),
                ("Confidence", prev.confidence_score, curr.confidence_score),
                ("Risk", prev.risk_score, curr.risk_score),
                ("Liquidity", prev.liquidity_score, curr.liquidity_score),
                ("Committee", prev.committee_decision, curr.committee_decision),
            )
            for label, prev_value, curr_value in field_specs:
                if prev_value == curr_value:
                    continue
                fields.append({"label": label, "prev": prev_value, "curr": curr_value})

        return {
            "available": True,
            "previous_computed_at": prev.computed_at.isoformat() if prev is not None else None,
            "current_computed_at": curr.computed_at.isoformat(),
            "fields": fields,
            "events": events,
        }

    async def get_market_brief(self) -> dict:
        """v8.0 "Market Control Center" -- synthesizes get_current_status()/
        get_what_changed()/get_ai_status() (already-computed sections) into
        direct answers to: is the market healthy, is risk increasing, did
        AI change its opinion, what are today's biggest changes, what
        needs attention now. No new data is fetched or computed -- this is
        purely a composition layer over three existing cheap reads."""
        current_status, what_changed, ai_status = await asyncio.gather(
            self.get_current_status(), self.get_what_changed(), self.get_ai_status()
        )
        return self._compose_market_brief(current_status, what_changed, ai_status)

    @staticmethod
    def _compose_market_brief(current_status: dict, what_changed: dict, ai_status: dict) -> dict:
        events_by_type = {e["event_type"]: e for e in what_changed["events"]}

        market_health = current_status["market_health"]
        is_healthy = {"Healthy": True, "Watch": None, "Stressed": False}.get(market_health)

        risk_event = events_by_type.get("RiskIncreased") or events_by_type.get("RiskReduced")
        if risk_event is not None:
            risk_direction = (
                "increasing" if risk_event["event_type"] == "RiskIncreased" else "decreasing"
            )
            risk_reason = risk_event["message"]
        else:
            risk_direction = "stable"
            risk_reason = "No material risk-score change since the last cycle."

        committee_event = events_by_type.get("CommitteeChanged")
        ai_opinion_changed = committee_event is not None
        if committee_event is not None:
            ai_opinion_reason = committee_event["message"]
        else:
            opinion = ai_status["committee_opinion"] or "no verdict yet"
            ai_opinion_reason = f"Committee opinion unchanged: {opinion}."

        biggest_changes_today = [e["message"] for e in what_changed["events"]]

        needs_attention: list[str] = []
        if risk_event is not None and risk_event["event_type"] == "RiskIncreased":
            needs_attention.append(risk_event["message"])
        if committee_event is not None:
            needs_attention.append(committee_event["message"])
        if market_health == "Stressed":
            needs_attention.append("Market health classification is Stressed.")
        if ai_status.get("highest_risk"):
            needs_attention.append(f"Highest scenario risk: {ai_status['highest_risk']}")
        if not needs_attention:
            needs_attention.append(
                "No urgent items -- market conditions are stable since the last cycle."
            )

        return {
            "is_market_healthy": is_healthy,
            "market_health_label": market_health,
            "risk_direction": risk_direction,
            "risk_reason": risk_reason,
            "ai_opinion_changed": ai_opinion_changed,
            "ai_opinion_reason": ai_opinion_reason,
            "biggest_changes_today": biggest_changes_today,
            "needs_attention": needs_attention,
            "computed_at": current_status["last_update"],
        }

    async def get_provider_status(self) -> list[dict]:
        from app.services.watchdog.provider_health import get_provider_status

        return await get_provider_status(self._session_factory, self._redis)

    async def get_alert_history(self, limit: int = _ALERT_HISTORY_LIMIT) -> list[dict]:
        # Reuses the existing Watchdog alert-history path verbatim (Memory
        # Engine's "alerts" category over AlertLog) -- kept exactly as is,
        # only re-surfaced here so /watchdog's combined dashboard doesn't
        # need a second round trip.
        engine = MemoryEngine(self._session_factory)
        return await engine.get_category("alerts", limit=limit)

    async def get_dashboard(self) -> dict:
        (
            current_status,
            market_overview,
            crypto_overview,
            macro_overview,
            onchain_overview,
            ai_status,
            what_changed,
            provider_status,
            alert_history,
        ) = await asyncio.gather(
            self.get_current_status(),
            self.get_market_overview(),
            self.get_crypto_overview(),
            self.get_macro_overview(),
            self.get_onchain_overview(),
            self.get_ai_status(),
            self.get_what_changed(),
            self.get_provider_status(),
            self.get_alert_history(),
        )
        return {
            "current_status": current_status,
            "market_brief": self._compose_market_brief(current_status, what_changed, ai_status),
            "market_overview": market_overview,
            "crypto_overview": crypto_overview,
            "macro_overview": macro_overview,
            "onchain_overview": onchain_overview,
            "ai_status": ai_status,
            "what_changed": what_changed,
            "provider_status": provider_status,
            "alert_history": alert_history,
        }

    # ------------------------------------------------------------ the cycle

    async def _safe_reliability(self) -> dict[str, float] | None:
        if self._reliability_engine is None:
            return None
        try:
            return await self._reliability_engine.evaluate_reliability()
        except Exception:
            return None

    async def _broadcast_event(self, event: dict) -> None:
        from app.telegram.broadcast import broadcast_text

        try:
            await broadcast_text(f"*WATCHDOG* ({event['event_type']})\n\n{event['message']}")
        except Exception:
            logger.warning(
                "Failed to broadcast watchdog event %s", event["event_type"], exc_info=True
            )

    async def _last_telegram_sent_at(self, event_type: str) -> datetime | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(WatchdogEvent.created_at)
                .where(
                    WatchdogEvent.event_type == event_type, WatchdogEvent.telegram_sent.is_(True)
                )
                .order_by(WatchdogEvent.created_at.desc())
                .limit(1)
            )

    async def _persist_and_notify(self, events: list[dict], now: datetime) -> int:
        notified = 0
        for event in events:
            telegram_sent = False
            if is_telegram_eligible(event["event_type"]):
                last_sent = await self._last_telegram_sent_at(event["event_type"])
                if not _is_on_cooldown(last_sent, now, _TELEGRAM_COOLDOWN_MINUTES):
                    await self._broadcast_event(event)
                    telegram_sent = True
                    notified += 1
            async with self._session_factory() as session:
                session.add(
                    WatchdogEvent(
                        event_type=event["event_type"],
                        message=event["message"],
                        data=event["data"],
                        telegram_sent=telegram_sent,
                    )
                )
                await session.commit()
        return notified

    async def run_cycle(self) -> WatchdogSnapshot:
        start = time.monotonic()
        now = datetime.now(UTC)

        previous_snapshot = await self.get_latest_snapshot()
        previous_dict = None
        if previous_snapshot is not None:
            previous_dict = {
                "regime": previous_snapshot.regime,
                "trend_strength_score": previous_snapshot.trend_strength_score,
                "confidence_score": previous_snapshot.confidence_score,
                "risk_score": previous_snapshot.risk_score,
                "liquidity_score": previous_snapshot.liquidity_score,
                "volatility": (
                    float(previous_snapshot.volatility)
                    if previous_snapshot.volatility is not None
                    else None
                ),
                "committee_decision": previous_snapshot.committee_decision,
            }

        regime_snapshot, global_score, scenario_snapshot, technical_btc = await asyncio.gather(
            self._regime_detector.get_latest(),
            self._global_score_engine.get_latest(),
            self._scenario_engine.get_latest(),
            self._technical_engine.get_latest("BTC"),
        )

        agent_outputs, reliability = await asyncio.gather(
            self._agent_orchestrator.run_all(),
            self._safe_reliability(),
        )
        consensus = compute_consensus(agent_outputs, reliability)
        committee = convene_committee(agent_outputs, consensus) if consensus is not None else None

        scenarios = scenario_snapshot.scenarios if scenario_snapshot is not None else None
        expected_scenario, expected_scenario_pct, highest_risk, biggest_opportunity = (
            scenario_extremes(scenarios)
        )

        global_score_value = global_score.global_score if global_score is not None else None
        volatility_value = (
            float(technical_btc.volatility)
            if technical_btc is not None and technical_btc.volatility is not None
            else None
        )

        current_dict = {
            "regime": regime_snapshot.regime.value if regime_snapshot is not None else None,
            "trend_strength_score": (
                global_score.trend_strength_score if global_score is not None else None
            ),
            "risk_score": global_score.risk_score if global_score is not None else None,
            "confidence_score": global_score.confidence_score if global_score is not None else None,
            "liquidity_score": global_score.liquidity_score if global_score is not None else None,
            "volatility": volatility_value,
            "committee_decision": committee.majority_decision if committee is not None else None,
        }

        row = WatchdogSnapshot(
            scan_duration_ms=round((time.monotonic() - start) * 1000, 2),
            regime=current_dict["regime"],
            market_health=classify_market_health(global_score_value),
            global_score=global_score_value,
            trend_strength_score=current_dict["trend_strength_score"],
            risk_score=current_dict["risk_score"],
            confidence_score=current_dict["confidence_score"],
            liquidity_score=current_dict["liquidity_score"],
            volatility=volatility_value,
            consensus=consensus.to_dict() if consensus is not None else None,
            committee_decision=current_dict["committee_decision"],
            committee_confidence_pct=committee.confidence_pct if committee is not None else None,
            committee_recommendation=(
                committee.final_recommendation if committee is not None else None
            ),
            expected_scenario=expected_scenario,
            expected_scenario_pct=expected_scenario_pct,
            highest_risk=highest_risk,
            biggest_opportunity=biggest_opportunity,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)

        events = detect_all_changes(previous_dict, current_dict)
        notified = await self._persist_and_notify(events, now)
        logger.info(
            "Watchdog cycle: %d change(s) detected, %d Telegram notification(s)",
            len(events),
            notified,
        )
        return row


def build_watchdog_engine() -> WatchdogEngine:
    from app.database.redis import get_redis
    from app.database.session import get_session_factory
    from app.services.agents.orchestrator import build_agent_orchestrator
    from app.services.etf.engine import ETFIntelligenceEngine
    from app.services.news.repository import NewsRepository
    from app.services.portfolio.advisor import PortfolioAdvisorEngine
    from app.services.portfolio.engine import PortfolioEngine
    from app.services.probability.engine import ProbabilityEngine
    from app.services.ranking.engine import RankingEngine
    from app.services.signals.engine import SignalEngine
    from app.services.technical.provider import TechnicalAnalysisProvider

    session_factory = get_session_factory()
    redis_client = get_redis()
    market_repository = MarketRepository(session_factory, redis_client)
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    scenario_engine = ScenarioEngine(session_factory, global_score_engine)
    whale_engine = WhaleIntelligenceEngine(session_factory)
    etf_engine = ETFIntelligenceEngine(news_repository, session_factory)
    portfolio_engine = PortfolioEngine(session_factory, market_repository)
    probability_engine = ProbabilityEngine(session_factory)
    portfolio_advisor = PortfolioAdvisorEngine(
        session_factory,
        signal_engine,
        probability_engine,
        portfolio_engine,
        RankingEngine(session_factory),
    )
    replay_engine = MarketReplayEngine(
        session_factory,
        market_repository,
        news_repository,
        regime_detector,
        global_score_engine,
        build_agent_orchestrator(),
        AgentReliabilityEngine(session_factory),
        portfolio_advisor,
        whale_engine,
        etf_engine,
        probability_engine,
    )
    technical_engine = TechnicalAnalysisEngine(
        session_factory, TechnicalAnalysisProvider(session_factory)
    )

    return WatchdogEngine(
        session_factory,
        market_repository,
        global_score_engine,
        regime_detector,
        scenario_engine,
        replay_engine,
        OnChainIntelligenceEngine(),
        whale_engine,
        technical_engine,
        build_agent_orchestrator(),
        AgentReliabilityEngine(session_factory),
        redis_client,
    )
