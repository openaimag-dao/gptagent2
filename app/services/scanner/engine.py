"""MarketScannerEngine -- the v5.5 Autonomous Market Scanner. Continuously
scans the crypto market (top ~500 by market cap plus the mission's
"always include" list), discovers unusual events, and publishes them into
the existing AlertLog table (alert_type prefixed "scanner:") -- exactly
the same "log every detection, notified or not" contract v5.1's
CriticalAlertEngine already established, so Watchdog's alert history,
Market Memory, and MarketReplayEngine's `alerts` field (which reads
AlertLog via MemoryEngine) all cover this system automatically, without
any new integration code, and without this engine bypassing Watchdog.

Escalation reuses v5.1's exact state machine (`decide_alert_action`,
`SEVERITY_ORDER`, `gate_severity`, `should_notify`) against a new
`ScannerAlert` episode table (mirrors `CriticalAlert`'s shape) so a
worsening tier on an active episode is one escalating alert, not a new
one each cycle (the mission's "BTC +3% -> no alert, BTC +5% -> one HIGH
alert, BTC +8% -> update previous alert, not a new one").

The AI filter reuses regime/consensus/committee alignment scoring
(`regime_alignment_score`, `consensus_alignment_score`,
`committee_alignment_score`, `score_alert_quality`) from the SAME
app.services.shocks.detectors module -- these are already generic pure
functions, not v5.1-specific, so calling them here is reuse, not
duplication. AI context (regime/committee/consensus/risk/confidence) is
read from the latest, already-computed WatchdogSnapshot (v5.4) rather
than running a second agent-orchestrator cycle.

IMPORTANT: this module never imports app.telegram.* and never sends a
Telegram message -- "Never send Telegram messages directly" from the
mission. `run_cycle()` returns every processed detection (with
`notify_eligible`/`action`/`tier`/`message`) for a separate notifier step
(app/services/scanner/notifier.py, invoked by the scheduler job) to act
on.
"""

import json
import logging
from datetime import UTC, datetime, timedelta

from redis.asyncio import Redis
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AlertLog, BreakoutEvent, ScannerAlert, ScannerSnapshot
from app.services.explanation.engine import ExplanationEngine, condense_explanation
from app.services.history.schemas import Timeframe
from app.services.scanner.breadth import compute_market_breadth
from app.services.scanner.detectors import (
    classify_price_event,
    detect_flash_move,
    detect_new_high_low,
    detect_sector_ecosystem_event,
    detect_support_resistance_break,
    detect_trend_change,
    detect_volatility_regime,
    detect_volume_multiple,
)
from app.services.scanner.provider import CoinGeckoMarketsClient
from app.services.scanner.sectors import classify_sector, compute_sector_breadth
from app.services.scanner.universe import ALWAYS_INCLUDE, ScannerUniverse
from app.services.shocks.detectors import (
    committee_alignment_score,
    compute_realized_volatility,
    consensus_alignment_score,
    decide_alert_action,
    detect_multi_asset_shock,
    gate_severity,
    regime_alignment_score,
    score_alert_quality,
    should_notify,
)
from app.services.technical.engine import TechnicalAnalysisEngine
from app.services.watchdog.engine import WatchdogEngine, build_watchdog_snapshot_insight

logger = logging.getLogger(__name__)

_HISTORY_LOOKBACK_HOURS = 30 * 24  # bounds "monthly breakout" queries
_RECENT_VOL_SAMPLE_SIZE = 6
_FLASH_MOVE_TIER = "critical"
_ABNORMAL_VOL_TIER = "high"
_VOL_EXPANSION_TIER = "important"
_LOW_VOL_TIER = "info"
_BREAKOUT_TIER = "important"
_NEW_HIGH_LOW_TIER = "info"
_CRYPTO_SHOCK_MIN_COUNT = 3
_CRYPTO_SHOCK_MIN_TIER = "important"
_TECHNICAL_PROXY_SYMBOLS = ("BTC", "ETH", "SOL")

_BREADTH_CACHE_KEY = "scanner:latest_breadth"
_SECTOR_BREADTH_CACHE_KEY = "scanner:latest_sector_breadth"
_BREADTH_CACHE_TTL_SECONDS = 3600


def _average(values: list[float]) -> float | None:
    values = [v for v in values if v is not None]
    return sum(values) / len(values) if values else None


class MarketScannerEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        universe: ScannerUniverse,
        markets_client: CoinGeckoMarketsClient,
        watchdog_engine: WatchdogEngine,
        technical_engine: TechnicalAnalysisEngine,
        redis_client: Redis | None = None,
        top_n: int = 500,
        explanation_engine: ExplanationEngine | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._universe = universe
        self._markets_client = markets_client
        self._watchdog_engine = watchdog_engine
        self._technical_engine = technical_engine
        self._redis = redis_client
        self._top_n = top_n
        self._explanation_engine = explanation_engine

    # ------------------------------------------------------------- fetching

    async def _fetch_markets(self, universe: list[dict]) -> dict[str, dict]:
        ids = [entry["coingecko_id"] for entry in universe]
        coins: list[dict] = []
        for start in range(0, len(ids), 250):
            batch_ids = ids[start : start + 250]
            coins.extend(await self._markets_client.fetch_by_ids(batch_ids))
        by_id = {c["id"]: c for c in coins}

        markets: dict[str, dict] = {}
        for entry in universe:
            coin = by_id.get(entry["coingecko_id"])
            if coin is None:
                continue
            markets[entry["symbol"]] = {
                "name": entry["name"],
                "price": coin.get("current_price"),
                "change_pct_1h": coin.get("price_change_percentage_1h_in_currency"),
                "change_pct_24h": coin.get("price_change_percentage_24h_in_currency"),
                "volume_24h": coin.get("total_volume"),
                "market_cap": coin.get("market_cap"),
                "market_cap_rank": entry.get("market_cap_rank"),
            }
        return markets

    def _build_readings(self, universe: list[dict], markets: dict[str, dict]) -> list[dict]:
        readings = []
        for entry in universe:
            data = markets.get(entry["symbol"])
            if data is None or data.get("price") is None:
                continue
            readings.append(
                {
                    "symbol": entry["symbol"],
                    "name": data["name"],
                    "price": float(data["price"]),
                    "change_pct_1h": data.get("change_pct_1h"),
                    "change_pct_24h": data.get("change_pct_24h"),
                    "volume_24h": data.get("volume_24h"),
                    "market_cap": data.get("market_cap"),
                    "market_cap_rank": data.get("market_cap_rank"),
                    "sector": classify_sector(entry["symbol"]),
                }
            )
        return readings

    # ------------------------------------------------------------ history

    async def _persist_snapshots(self, readings: list[dict], now: datetime) -> None:
        async with self._session_factory() as session:
            for reading in readings:
                session.add(
                    ScannerSnapshot(
                        symbol=reading["symbol"],
                        name=reading["name"],
                        price=reading["price"],
                        change_pct_1h=reading["change_pct_1h"],
                        change_pct_24h=reading["change_pct_24h"],
                        volume_24h=reading["volume_24h"],
                        market_cap=reading["market_cap"],
                        market_cap_rank=reading["market_cap_rank"],
                        sector=reading["sector"],
                        recorded_at=now,
                    )
                )
            await session.commit()

    async def _history_by_symbol(
        self, symbols: list[str], now: datetime
    ) -> dict[str, list[ScannerSnapshot]]:
        since = now - timedelta(hours=_HISTORY_LOOKBACK_HOURS)
        async with self._session_factory() as session:
            rows = list(
                await session.scalars(
                    select(ScannerSnapshot)
                    .where(
                        ScannerSnapshot.symbol.in_(symbols), ScannerSnapshot.recorded_at >= since
                    )
                    .order_by(ScannerSnapshot.recorded_at.asc())
                )
            )
        by_symbol: dict[str, list[ScannerSnapshot]] = {s: [] for s in symbols}
        for row in rows:
            by_symbol[row.symbol].append(row)
        return by_symbol

    async def _latest_breakout_events(self) -> dict[str, BreakoutEvent]:
        """v12.0 P1 -- BreakoutEngine already runs a 6-signal-confirmed
        breakout/breakdown/retest/liquidity-sweep detection (volume, ATR,
        VWAP, regime, OI/funding, multi-timeframe) on its own schedule for
        the curated crypto symbols it tracks (BTC/ETH/SOL -- the crypto
        subset of app.scheduler.jobs.FEATURE_SYMBOLS), a materially
        stronger signal than this engine's own bare
        price-vs-period-extreme check (detect_new_high_low). One cheap
        read of already-persisted rows -- no BreakoutEngine construction,
        no new computation, no per-symbol query."""
        cutoff = datetime.now(UTC) - timedelta(hours=48)
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(BreakoutEvent)
                .where(
                    BreakoutEvent.timeframe == Timeframe.DAILY.value,
                    BreakoutEvent.computed_at >= cutoff,
                )
                .order_by(BreakoutEvent.computed_at.desc())
            )
            latest: dict[str, BreakoutEvent] = {}
            for row in rows:
                latest.setdefault(row.symbol, row)  # desc order -> first seen is most recent
            return latest

    # ------------------------------------------------------------ AI filter

    async def get_market_context(self) -> dict:
        """The single place that turns the latest WatchdogSnapshot (v5.4 --
        already-computed regime/risk/confidence/committee/consensus AND
        Scenario Engine's expected_scenario/highest_risk/
        biggest_opportunity, all persisted once per Watchdog cycle) into a
        plain dict. Every consumer shares this exact same shaping logic
        instead of re-deriving it: run_cycle()'s AI-filter alignment
        scoring (_alignment_components() only reads a subset of these
        keys), each detection's attached context (so a fired Telegram
        alert can show Expected Scenario/Highest Risk/Biggest Opportunity,
        not just regime/risk/committee), and the dashboard/API/Telegram-
        facing reads (app/api/scanner.py, format_scanner_dashboard()).
        get_latest_snapshot() is a single cached-row SELECT, not a fresh
        agent-orchestrator run, so calling this on every dashboard/API/
        Telegram request is cheap and introduces no duplicate computation
        -- the expensive part (the 6-agent orchestrator cycle) still runs
        exactly once, on Watchdog's own schedule."""
        snapshot = await self._watchdog_engine.get_latest_snapshot()
        if snapshot is None:
            return {
                "regime": None,
                "market_health": None,
                "risk_score": None,
                "confidence_score": None,
                "trend_strength_score": None,
                "committee_decision": None,
                "committee_majority_pct": None,
                "consensus": None,
                "expected_scenario": None,
                "expected_scenario_pct": None,
                "highest_risk": None,
                "biggest_opportunity": None,
                "computed_at": None,
                "ai_insight": build_watchdog_snapshot_insight(None),
            }
        consensus = snapshot.consensus or {}
        return {
            "regime": snapshot.regime,
            "market_health": snapshot.market_health,
            "risk_score": snapshot.risk_score,
            "confidence_score": snapshot.confidence_score,
            "trend_strength_score": snapshot.trend_strength_score,
            "committee_decision": snapshot.committee_decision,
            # committee_confidence_pct is a Numeric(6,2) column -- asyncpg
            # returns decimal.Decimal for it, which breaks weighted_average's
            # float multiplication in score_alert_quality() if passed through
            # unconverted (Decimal * float raises TypeError). Cast at the
            # DB-row boundary, same as every other Decimal-column read in
            # this codebase (e.g. universe.py's float(data["price"])).
            "committee_majority_pct": (
                float(snapshot.committee_confidence_pct)
                if snapshot.committee_confidence_pct is not None
                else None
            ),
            "consensus": consensus or None,
            "expected_scenario": snapshot.expected_scenario,
            "expected_scenario_pct": snapshot.expected_scenario_pct,
            "highest_risk": snapshot.highest_risk,
            "biggest_opportunity": snapshot.biggest_opportunity,
            "computed_at": snapshot.computed_at.isoformat() if snapshot.computed_at else None,
            "ai_insight": build_watchdog_snapshot_insight(snapshot),
        }

    def _alignment_components(self, ctx: dict, move_direction: str) -> dict:
        consensus = ctx["consensus"]
        return {
            "regime_alignment": regime_alignment_score(ctx["regime"], move_direction),
            "consensus_alignment": (
                consensus_alignment_score(
                    consensus.get("bullish_pct"),
                    consensus.get("bearish_pct"),
                    consensus.get("agreement_score"),
                    move_direction,
                )
                if consensus
                else None
            ),
            "committee_alignment": (
                committee_alignment_score(
                    ctx["committee_decision"], ctx["committee_majority_pct"], move_direction
                )
                if ctx["committee_decision"] is not None
                else None
            ),
            "risk_score": ctx["risk_score"],
            "confidence_score": ctx["confidence_score"],
        }

    # -------------------------------------------------------- per-symbol scan

    def _scan_symbol(
        self,
        reading: dict,
        history: list[ScannerSnapshot],
        breakout_event: BreakoutEvent | None = None,
    ) -> dict:
        symbol = reading["symbol"]
        prices = [float(h.price) for h in history] + [reading["price"]]
        volumes = [float(h.volume_24h) for h in history if h.volume_24h is not None]

        price_event = classify_price_event(symbol, reading["change_pct_24h"])
        volume_event = detect_volume_multiple(
            reading["volume_24h"], _average(volumes[:-1] or volumes)
        )

        recent_vol = compute_realized_volatility(prices[-_RECENT_VOL_SAMPLE_SIZE:])
        baseline_vol = compute_realized_volatility(prices)
        volatility_label = detect_volatility_regime(recent_vol, baseline_vol)
        flash_label = detect_flash_move(reading["change_pct_1h"])

        period_high = max(prices[:-1]) if len(prices) > 1 else None
        period_low = min(prices[:-1]) if len(prices) > 1 else None
        if breakout_event is not None:
            # BreakoutEngine's 6-signal-confirmed read supersedes the bare
            # price-vs-period-extreme check for the handful of symbols it
            # tracks -- see _latest_breakout_events().
            breakout_label = (
                f"{breakout_event.event_type.replace('_', ' ').title()} "
                f"({breakout_event.direction})"
            )
        else:
            breakout_label = detect_new_high_low(reading["price"], period_high, period_low)
        sr_label = detect_support_resistance_break(reading["price"], period_low, period_high)

        return {
            "price_event": price_event,
            "volume_event": volume_event,
            "flash_label": flash_label,
            "volatility_label": volatility_label,
            "breakout_label": breakout_label,
            "sr_label": sr_label,
        }

    async def _technical_trend_events(self, symbols: list[str]) -> dict[str, str | None]:
        events: dict[str, str | None] = {}
        for symbol in symbols:
            if symbol not in _TECHNICAL_PROXY_SYMBOLS:
                continue
            try:
                latest = await self._technical_engine.get_latest(symbol)
            except Exception:
                latest = None
            if latest is None:
                continue
            events[symbol] = detect_trend_change(None, float(latest.trend_strength or 0))
        return events

    # ------------------------------------------------------------ envelopes

    def _worst_signal_tier(self, scan: dict) -> tuple[str | None, list[str]]:
        """When a symbol has no price event of its own but a strong
        volatility/breakout signal fired, that signal becomes the primary
        (and only) tier driver for this cycle -- otherwise the price
        event's own 4-tier ladder is primary and everything else is
        corroboration folded into the message/quality components."""
        tags = []
        if scan["flash_label"]:
            tags.append(scan["flash_label"])
        if scan["volatility_label"]:
            tags.append(scan["volatility_label"])
        if scan["breakout_label"]:
            tags.append(scan["breakout_label"])
        if scan["sr_label"]:
            tags.append(scan["sr_label"])
        if scan["volume_event"]:
            tags.append(scan["volume_event"]["label"])

        if scan["price_event"] is not None:
            return scan["price_event"]["tier"], tags

        if scan["flash_label"]:
            return _FLASH_MOVE_TIER, tags
        if scan["volatility_label"] == "Abnormal Volatility":
            return _ABNORMAL_VOL_TIER, tags
        if scan["volatility_label"] == "Volatility Expansion":
            return _VOL_EXPANSION_TIER, tags
        if scan["breakout_label"] or scan["sr_label"]:
            return _BREAKOUT_TIER, tags
        if scan["volatility_label"] == "Low Volatility Compression":
            return _LOW_VOL_TIER, tags
        return None, tags

    async def _process_detections(self, envelopes: list[dict], now: datetime) -> list[dict]:
        """Batched replacement for the old per-envelope _process_detection:
        that version opened up to 4 separate DB round trips (existing-alert
        lookup, resolve, insert/escalate, AlertLog insert) for EVERY
        qualifying envelope -- during a market-wide move (exactly when the
        crypto-shock/sector detectors are meant to fire), dozens of
        envelopes could serialize through 3-4 sequential transactions each
        in a single scan cycle. This does one SELECT for every envelope's
        existing active alert and one write transaction for the whole
        batch, preserving the exact same per-envelope decision logic and
        result shape/order."""
        if not envelopes:
            return []

        alert_keys = [envelope["alert_key"] for envelope in envelopes]
        async with self._session_factory() as session:
            rows = list(
                await session.scalars(
                    select(ScannerAlert).where(
                        ScannerAlert.alert_key.in_(alert_keys), ScannerAlert.active.is_(True)
                    )
                )
            )
        existing_by_key: dict[str, ScannerAlert] = {}
        for row in rows:
            current = existing_by_key.get(row.alert_key)
            if current is None or row.last_updated_at > current.last_updated_at:
                existing_by_key[row.alert_key] = row

        decisions = []
        for envelope in envelopes:
            existing = existing_by_key.get(envelope["alert_key"])
            quality_score = score_alert_quality(envelope["quality_components"])
            tier = gate_severity(envelope["raw_tier"], quality_score)
            action = decide_alert_action(
                existing_active=existing is not None,
                existing_tier=existing.tier if existing is not None else None,
                new_tier=tier,
                now=now,
                last_updated_at=existing.last_updated_at if existing is not None else None,
            )
            resolve_id = existing.id if action == "resolve_then_new" else None
            escalate_id = existing.id if action == "escalate" else None
            if action == "resolve_then_new":
                action = "new"
            decisions.append(
                {
                    "envelope": envelope,
                    "quality_score": quality_score,
                    "tier": tier,
                    "action": action,
                    "resolve_id": resolve_id,
                    "escalate_id": escalate_id,
                }
            )

        # v12.0 P1 -- ExplanationEngine's evidence pack was never referenced
        # from Scanner's own alerts (only /why ever showed it). Attached
        # only for HIGH/CRITICAL alerts that will actually reach a user
        # (never for suppressed/info-tier detections) -- unavoidably
        # sequential (each is its own analysis-engine call, not a DB round
        # trip) and never allowed to break the core alert pipeline if it
        # fails.
        for decision in decisions:
            envelope, tier, action = decision["envelope"], decision["tier"], decision["action"]
            if (
                self._explanation_engine is not None
                and tier in ("high", "critical")
                and action != "suppress"
                and envelope.get("symbols")
            ):
                try:
                    evidence = await self._explanation_engine.build(envelope["symbols"][0])
                    why = condense_explanation(evidence)
                    if why:
                        envelope["message"] = f"{envelope['message']}\n{why}"
                except Exception:
                    logger.exception(
                        "Explanation evidence pack failed for %s", envelope["symbols"][0]
                    )

        resolve_ids = [d["resolve_id"] for d in decisions if d["resolve_id"] is not None]
        new_alerts = [
            ScannerAlert(
                alert_key=d["envelope"]["alert_key"],
                category=d["envelope"]["category"],
                tier=d["tier"],
                symbols=d["envelope"]["symbols"],
                message=d["envelope"]["message"],
                telegram_message_ids={},
                active=True,
                data={"quality_score": d["quality_score"], **d["envelope"]["data"]},
                first_triggered_at=now,
                last_updated_at=now,
            )
            for d in decisions
            if d["action"] == "new"
        ]
        escalate_updates = [
            {
                "id": d["escalate_id"],
                "tier": d["tier"],
                "message": d["envelope"]["message"],
                "last_updated_at": now,
                "data": {"quality_score": d["quality_score"], **d["envelope"]["data"]},
            }
            for d in decisions
            if d["action"] == "escalate"
        ]
        alert_logs = [
            AlertLog(
                alert_type=f"scanner:{d['envelope']['category']}",
                message=d["envelope"]["message"],
                conviction_tier=d["tier"],
                confidence_pct=round(d["quality_score"]) if d["quality_score"] is not None else 0,
                broadcast=False,  # set True by the notifier if it actually sends
                data={"alert_key": d["envelope"]["alert_key"], "symbols": d["envelope"]["symbols"]},
            )
            for d in decisions
        ]

        async with self._session_factory() as session:
            if resolve_ids:
                await session.execute(
                    update(ScannerAlert)
                    .where(ScannerAlert.id.in_(resolve_ids))
                    .values(active=False, resolved_at=now)
                )
            if new_alerts:
                session.add_all(new_alerts)
            if escalate_updates:
                await session.execute(update(ScannerAlert), escalate_updates)
            session.add_all(alert_logs)
            await session.flush()
            log_ids = [log_row.id for log_row in alert_logs]
            await session.commit()

        results = []
        for decision, alert_log_id in zip(decisions, log_ids, strict=True):
            envelope, tier, action = decision["envelope"], decision["tier"], decision["action"]
            results.append(
                {
                    "alert_key": envelope["alert_key"],
                    "alert_log_id": alert_log_id,
                    "category": envelope["category"],
                    "symbols": envelope["symbols"],
                    "tier": tier,
                    "quality_score": decision["quality_score"],
                    "action": action,
                    "notify_eligible": should_notify(tier) and action in ("new", "escalate"),
                    "message": envelope["message"],
                    "title": envelope.get("title"),
                    "direction": envelope.get("direction"),
                    "readings": envelope.get("readings", []),
                    "context": envelope.get("context_summary", {}),
                }
            )
        return results

    # --------------------------------------------------------------- cycle

    async def run_cycle(self) -> dict:
        now = datetime.now(UTC)
        universe = await self._universe.get_universe(top_n=self._top_n)
        markets = await self._fetch_markets(universe)
        readings = self._build_readings(universe, markets)
        if not readings:
            return {"processed": [], "breadth": None, "sector_breadth": [], "universe_size": 0}

        await self._persist_snapshots(readings, now)
        history_by_symbol = await self._history_by_symbol([r["symbol"] for r in readings], now)
        breakout_events = await self._latest_breakout_events()

        scans = {
            r["symbol"]: self._scan_symbol(
                r, history_by_symbol[r["symbol"]], breakout_events.get(r["symbol"])
            )
            for r in readings
        }
        price_events = {symbol: scan["price_event"] for symbol, scan in scans.items()}

        breadth = compute_market_breadth(readings)
        sector_breadth = compute_sector_breadth(readings)

        symbols_by_sector: dict[str, list[str]] = {}
        for reading in readings:
            symbols_by_sector.setdefault(reading["sector"], []).append(reading["symbol"])

        ctx = await self.get_market_context()

        envelopes: list[dict] = []
        handled_symbols: set[str] = set()

        shock = detect_multi_asset_shock(
            price_events,
            symbols=tuple(ALWAYS_INCLUDE.keys()),
            min_count=_CRYPTO_SHOCK_MIN_COUNT,
            min_tier=_CRYPTO_SHOCK_MIN_TIER,
            category="crypto_market_shock",
        )
        if shock is not None:
            handled_symbols = {m["symbol"] for m in shock["moves"]}
            move_direction = "bullish" if shock["direction"] == "up" else "bearish"
            envelope = {
                "alert_key": f"scanner:crypto_market_shock:{shock['direction']}",
                "category": "crypto_market_shock",
                "symbols": [m["symbol"] for m in shock["moves"]],
                "raw_tier": shock["tier"],
                "title": "CRYPTO MARKET SHOCK",
                "direction": shock["direction"],
                "readings": shock["moves"],
                "quality_components": self._alignment_components(ctx, move_direction),
                "message": (
                    f"CRYPTO MARKET SHOCK ({shock['direction']}): "
                    + ", ".join(f"{m['symbol']} {m['pct_change']:+.2f}%" for m in shock["moves"])
                ),
                "data": {"moves": shock["moves"]},
                "context_summary": ctx,
            }
            envelopes.append(envelope)

        for sector_row in sector_breadth:
            members = symbols_by_sector.get(sector_row["sector"], [])
            member_events = [price_events.get(s) for s in members]
            event = detect_sector_ecosystem_event(
                sector_row["sector"], sector_row["avg_change_pct_24h"], member_events
            )
            if event is None:
                continue
            move_direction = "bullish" if event["direction"] == "up" else "bearish"
            raw_tier = "high" if len(event["corroborating_symbols"]) >= 2 else "important"
            envelope = {
                "alert_key": f"scanner:sector_ecosystem:{event['sector']}:{event['direction']}",
                "category": "sector_ecosystem",
                "symbols": event["corroborating_symbols"],
                "raw_tier": raw_tier,
                "title": event["title"],
                "direction": event["direction"],
                "readings": [],
                "quality_components": self._alignment_components(ctx, move_direction),
                "message": (
                    f"{event['title']}: {event['sector']} sector avg "
                    f"{event['avg_change_pct_24h']:+.2f}% (24h), led by "
                    f"{', '.join(event['corroborating_symbols'][:5])}"
                ),
                "data": event,
                "context_summary": ctx,
            }
            envelopes.append(envelope)

        technical_trends = await self._technical_trend_events([r["symbol"] for r in readings])

        for reading in readings:
            symbol = reading["symbol"]
            if symbol in handled_symbols:
                continue
            scan = scans[symbol]
            tier, tags = self._worst_signal_tier(scan)
            trend_tag = technical_trends.get(symbol)
            if trend_tag:
                tags = [*tags, trend_tag]
            if tier is None:
                continue

            direction = (
                scan["price_event"]["direction"]
                if scan["price_event"] is not None
                else ("up" if (reading["change_pct_24h"] or 0) >= 0 else "down")
            )
            move_direction = "bullish" if direction == "up" else "bearish"

            components = {
                "volume": (
                    min(100.0, scan["volume_event"]["multiple"] * 20)
                    if scan["volume_event"]
                    else None
                ),
                **self._alignment_components(ctx, move_direction),
            }

            change_str = (
                f"{reading['change_pct_24h']:+.2f}%"
                if reading["change_pct_24h"] is not None
                else "n/a"
            )
            # v8.0 AI Market Brief: fold in signals already computed by
            # this same scan (volatility_label from _scan_symbol()) and
            # the most recent prior ScannerSnapshot row (already fetched
            # into history_by_symbol above for the tier detectors) instead
            # of only ever showing the bare 24h price move.
            message_parts = [
                f"{symbol} {change_str} (24h) -- now {reading['price']:,.4f}.",
                f"Signals: {', '.join(tags) if tags else 'price move'}.",
            ]
            if scan["volatility_label"]:
                message_parts.append(f"Volatility: {scan['volatility_label']}.")
            prior_history = history_by_symbol[symbol]
            if prior_history:
                prev_price = float(prior_history[-1].price)
                if prev_price:
                    pct_since_prev = (reading["price"] - prev_price) / prev_price * 100
                    prev_time = prior_history[-1].recorded_at.strftime("%H:%M UTC")
                    message_parts.append(f"Since last scan ({prev_time}): {pct_since_prev:+.2f}%.")

            envelope = {
                "alert_key": f"scanner:price_event:{symbol}:{direction}",
                "category": "price_event",
                "symbols": [symbol],
                "raw_tier": tier,
                "title": f"{symbol} {'SURGE' if direction == 'up' else 'DROP'}",
                "direction": direction,
                "readings": [
                    {
                        "symbol": symbol,
                        "price": reading["price"],
                        "change_pct_24h": reading["change_pct_24h"],
                        "change_pct_1h": reading["change_pct_1h"],
                        "volume_24h": reading["volume_24h"],
                    }
                ],
                "quality_components": components,
                "message": " ".join(message_parts),
                "data": {"tags": tags, "sector": reading["sector"]},
                "context_summary": ctx,
            }
            envelopes.append(envelope)

        processed = await self._process_detections(envelopes, now)

        await self._cache_breadth(breadth, sector_breadth)

        return {
            "processed": processed,
            "breadth": breadth,
            "sector_breadth": sector_breadth,
            "universe_size": len(readings),
        }

    async def _cache_breadth(self, breadth: dict, sector_breadth: list[dict]) -> None:
        # Cached (not recomputed on every dashboard/API read) so a page
        # view never triggers a fresh CoinGecko fetch -- "Avoid unnecessary
        # API requests" from the mission.
        if self._redis is None:
            return
        await self._redis.set(
            _BREADTH_CACHE_KEY, json.dumps(breadth), ex=_BREADTH_CACHE_TTL_SECONDS
        )
        await self._redis.set(
            _SECTOR_BREADTH_CACHE_KEY, json.dumps(sector_breadth), ex=_BREADTH_CACHE_TTL_SECONDS
        )

    async def get_latest_breadth(self) -> dict | None:
        if self._redis is None:
            return None
        cached = await self._redis.get(_BREADTH_CACHE_KEY)
        return json.loads(cached) if cached else None

    async def get_latest_sector_breadth(self) -> list[dict]:
        if self._redis is None:
            return []
        cached = await self._redis.get(_SECTOR_BREADTH_CACHE_KEY)
        return json.loads(cached) if cached else []

    async def list_suppressed_alerts(self, limit: int = 50) -> list[AlertLog]:
        """Scanner detections that were logged but never reached Telegram
        -- either they never cleared the conviction gate (tier below high/
        critical) or an active episode's cooldown suppressed a repeat.
        Reads the same AlertLog table every other Watchdog/Memory view
        already reads."""
        async with self._session_factory() as session:
            return list(
                await session.scalars(
                    select(AlertLog)
                    .where(
                        AlertLog.alert_type.like("scanner:%"),
                        AlertLog.broadcast.is_(False),
                    )
                    .order_by(AlertLog.triggered_at.desc())
                    .limit(limit)
                )
            )

    # ------------------------------------------------------------- reads

    async def get_latest_snapshots(self, limit: int = 50) -> list[ScannerSnapshot]:
        async with self._session_factory() as session:
            latest_recorded_at = await session.scalar(
                select(ScannerSnapshot.recorded_at)
                .order_by(ScannerSnapshot.recorded_at.desc())
                .limit(1)
            )
            if latest_recorded_at is None:
                return []
            rows = await session.scalars(
                select(ScannerSnapshot)
                .where(ScannerSnapshot.recorded_at == latest_recorded_at)
                .order_by(ScannerSnapshot.market_cap_rank.asc().nulls_last())
                .limit(limit)
            )
            return list(rows)

    async def list_active_alerts(self) -> list[ScannerAlert]:
        async with self._session_factory() as session:
            return list(
                await session.scalars(
                    select(ScannerAlert)
                    .where(ScannerAlert.active.is_(True))
                    .order_by(ScannerAlert.last_updated_at.desc())
                )
            )

    async def list_recent_alerts(self, limit: int = 50) -> list[ScannerAlert]:
        async with self._session_factory() as session:
            return list(
                await session.scalars(
                    select(ScannerAlert).order_by(ScannerAlert.last_updated_at.desc()).limit(limit)
                )
            )


def build_market_scanner_engine() -> MarketScannerEngine:
    from app.database.redis import get_redis
    from app.database.session import get_session_factory
    from app.services.analysis.regime import RegimeDetector
    from app.services.global_score.engine import GlobalScoreEngine
    from app.services.market.repository import MarketRepository
    from app.services.news.repository import NewsRepository
    from app.services.scenarios.engine import ScenarioEngine
    from app.services.signals.engine import SignalEngine
    from app.services.technical.provider import TechnicalAnalysisProvider
    from app.services.watchdog.engine import build_watchdog_engine

    session_factory = get_session_factory()
    redis_client = get_redis()
    markets_client = CoinGeckoMarketsClient()
    universe = ScannerUniverse(markets_client, redis_client)
    technical_engine = TechnicalAnalysisEngine(
        session_factory, TechnicalAnalysisProvider(session_factory)
    )
    market_repository = MarketRepository(session_factory, redis_client)
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    explanation_engine = ExplanationEngine(
        session_factory,
        signal_engine,
        regime_detector,
        news_repository,
        global_score_engine,
        ScenarioEngine(session_factory, global_score_engine),
    )
    return MarketScannerEngine(
        session_factory,
        universe,
        markets_client,
        build_watchdog_engine(),
        technical_engine,
        redis_client,
        explanation_engine=explanation_engine,
    )
