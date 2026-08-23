"""Configurable Alerts (v4.0 Phase 8) -- user-defined threshold rules that
complement the Smart Alert Engine's fixed detectors (engine.py/detectors.py)
rather than replacing them: those fire on deltas the platform decided
matter; a rule here fires when a metric *the user picked* crosses a
threshold *the user picked*, and notifies only the chat that created it.

Reuses existing engines for every metric reading -- MarketRepository for
price, ProbabilityEngine/BreakoutEngine for the two per-symbol model
outputs, GlobalScoreEngine for the two global scores -- so no new data
fetching or indicator math is introduced. A metric that can't be resolved
(engine not configured, symbol not synced yet) honestly skips the rule
for that cycle rather than guessing.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AlertLog, AlertRule
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.analysis.regime import RegimeDetector
from app.services.breakout.engine import BreakoutEngine
from app.services.features.engine import FeatureEngine
from app.services.global_score.engine import GlobalScoreEngine
from app.services.history.schemas import Timeframe
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.probability.engine import ProbabilityEngine
from app.services.signals.engine import SignalEngine

logger = logging.getLogger(__name__)

VALID_METRICS: tuple[str, ...] = (
    "price",
    "change_pct_24h",
    "probability_edge",
    "breakout_probability",
    "risk_off_score",
    "liquidity_score",
)
GLOBAL_METRICS: tuple[str, ...] = ("risk_off_score", "liquidity_score")
VALID_OPERATORS: tuple[str, ...] = ("above", "below")


def evaluate_condition(value: float, operator: str, threshold: float) -> bool:
    """Pure function: does `value` breach `threshold` per `operator`?"""
    return value > threshold if operator == "above" else value < threshold


def is_rule_on_cooldown(
    last_triggered_at: datetime | None, now: datetime, cooldown_minutes: int
) -> bool:
    """Pure function, mirrors AlertEngine's `_is_on_cooldown`."""
    if last_triggered_at is None:
        return False
    return now - last_triggered_at < timedelta(minutes=cooldown_minutes)


class AlertRuleEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        market_repository: MarketRepository,
        probability_engine: ProbabilityEngine,
        breakout_engine: BreakoutEngine,
        global_score_engine: GlobalScoreEngine,
    ) -> None:
        self._session_factory = session_factory
        self._market_repository = market_repository
        self._probability_engine = probability_engine
        self._breakout_engine = breakout_engine
        self._global_score_engine = global_score_engine

    async def create_rule(
        self,
        chat_id: str,
        symbol: str,
        metric: str,
        operator: str,
        threshold: float,
        cooldown_minutes: int = 60,
    ) -> AlertRule:
        if metric not in VALID_METRICS:
            raise ValueError(f"Unknown metric {metric!r}; expected one of {VALID_METRICS}")
        if operator not in VALID_OPERATORS:
            raise ValueError(f"Unknown operator {operator!r}; expected one of {VALID_OPERATORS}")
        row = AlertRule(
            chat_id=chat_id,
            symbol=symbol.upper(),
            metric=metric,
            operator=operator,
            threshold=threshold,
            cooldown_minutes=cooldown_minutes,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def list_rules(self, chat_id: str) -> list[AlertRule]:
        async with self._session_factory() as session:
            return list(
                await session.scalars(
                    select(AlertRule)
                    .where(AlertRule.chat_id == chat_id)
                    .order_by(AlertRule.created_at.desc())
                )
            )

    async def delete_rule(self, rule_id: int, chat_id: str) -> bool:
        async with self._session_factory() as session:
            row = await session.get(AlertRule, rule_id)
            if row is None or row.chat_id != chat_id:
                return False
            await session.delete(row)
            await session.commit()
        return True

    async def recent_history(self, chat_id: str, limit: int = 20) -> list[dict]:
        async with self._session_factory() as session:
            rows = list(
                await session.scalars(
                    select(AlertLog)
                    .where(AlertLog.alert_type.like("custom_rule:%"))
                    .order_by(AlertLog.triggered_at.desc())
                    .limit(200)
                )
            )
        return [row.data for row in rows if row.data.get("chat_id") == chat_id][:limit]

    async def _resolve_metric(self, symbol: str, metric: str) -> float | None:
        if metric == "price":
            assets = await self._market_repository.get_latest()
            asset = next((a for a in assets if a.symbol == symbol), None)
            return float(asset.price) if asset is not None else None
        if metric == "change_pct_24h":
            # Same 24h change every quote card already shows -- lets a user
            # set e.g. "/setalert BTC change_pct_24h above 3" and
            # "/setalert BTC change_pct_24h below -3" for a sharp-move alert
            # in either direction, reusing the market data this engine
            # already fetches for the "price" metric above.
            assets = await self._market_repository.get_latest()
            asset = next((a for a in assets if a.symbol == symbol), None)
            if asset is None or asset.change_pct_24h is None:
                return None
            return float(asset.change_pct_24h)
        if metric == "probability_edge":
            snapshot = await self._probability_engine.get_latest(symbol, Timeframe.DAILY)
            if snapshot is None:
                return None
            return snapshot.prob_up_pct - snapshot.prob_down_pct
        if metric == "breakout_probability":
            event = await self._breakout_engine.get_latest(symbol, Timeframe.DAILY)
            if event is None or event.probability_pct is None:
                return None
            return float(event.probability_pct)
        if metric in GLOBAL_METRICS:
            score = await self._global_score_engine.get_latest()
            if score is None:
                return None
            return float(getattr(score, metric))
        return None

    async def evaluate_all(self) -> list[dict]:
        """Checks every enabled rule once, sends a targeted Telegram message
        for each breach not on cooldown, and logs it to AlertLog (reusing the
        Smart Alert Engine's audit table with an `alert_type` prefix that
        keeps the two systems' entries distinguishable). Returns the fired
        triggers."""
        # Imported here, not at module scope, to avoid a circular import:
        # app.telegram.handlers imports this module (for the /setalert
        # command family), and app.telegram.broadcast imports
        # app.telegram.bot, which imports app.telegram.handlers.
        from app.telegram.broadcast import send_text_to

        now = datetime.now(UTC)
        async with self._session_factory() as session:
            query = select(AlertRule).where(AlertRule.enabled.is_(True))
            rules = list(await session.scalars(query))

        fired = []
        for rule in rules:
            if is_rule_on_cooldown(rule.last_triggered_at, now, rule.cooldown_minutes):
                continue
            value = await self._resolve_metric(rule.symbol, rule.metric)
            if value is None:
                continue
            threshold = float(rule.threshold)
            if not evaluate_condition(value, rule.operator, threshold):
                continue

            message = (
                f"*Custom Alert*: {rule.symbol} {rule.metric.replace('_', ' ')} is "
                f"{value:.2f}, {rule.operator} your threshold of {threshold:.2f}."
            )
            try:
                broadcast_ok = await send_text_to(int(rule.chat_id), message)
            except Exception:
                logger.warning("Failed to send custom alert for rule %s", rule.id, exc_info=True)
                broadcast_ok = False

            trigger = {
                "rule_id": rule.id,
                "chat_id": rule.chat_id,
                "symbol": rule.symbol,
                "metric": rule.metric,
                "operator": rule.operator,
                "threshold": threshold,
                "value": value,
            }
            async with self._session_factory() as session:
                session.add(
                    AlertLog(
                        alert_type=f"custom_rule:{rule.metric}",
                        message=message,
                        conviction_tier="custom",
                        confidence_pct=100,
                        broadcast=broadcast_ok,
                        data=trigger,
                    )
                )
                row = await session.get(AlertRule, rule.id)
                if row is not None:
                    row.last_triggered_at = now
                await session.commit()
            fired.append(trigger)

        return fired


def build_alert_rule_engine() -> AlertRuleEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    feature_engine = FeatureEngine(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    return AlertRuleEngine(
        session_factory,
        market_repository,
        ProbabilityEngine(session_factory),
        BreakoutEngine(session_factory, regime_detector, feature_engine),
        GlobalScoreEngine(session_factory, market_repository, regime_detector, signal_engine),
    )
