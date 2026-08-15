"""Alert Performance Analytics (V9 Increment 9) -- grades AlertLog entries
against what price actually did afterward, the same index-by-timestamp
join pattern LearningEngine/ForecastEngine/AgentReliabilityEngine already
use for "what actually happened next" (never a second, different notion of
ground truth). Reuses find_symbol_config/get_series for history lookup --
no new data source.

AlertLog rows are written by four different systems (Smart Alert Engine,
AlertRuleEngine, the v5.1 Critical Alert System, the v5.5 Market Scanner)
with different `data` JSON shapes, so this module resolves a symbol/
direction from each row's `data` on a best-effort basis
(resolve_alert_symbol/resolve_alert_direction) rather than assuming one
canonical shape. An alert whose `data` has no resolvable symbol is simply
never graded -- there is no fallback guess.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import AlertLog, AlertPerformanceGrade
from app.services.history.registry import find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe

_UP_ALIASES = {"up", "bullish"}
_DOWN_ALIASES = {"down", "bearish"}


def resolve_alert_symbol(data: dict) -> str | None:
    """Pure function: best-effort primary symbol for an AlertLog row's own
    `data` JSON -- checks the shapes this project's four alert-producing
    systems actually write, in order, never guesses beyond them. Multi-
    symbol alerts (e.g. a crypto-market-shock covering several symbols)
    are graded against their first-listed symbol only -- a documented
    simplification, not a fabricated aggregate."""
    if not isinstance(data, dict):
        return None
    symbols = data.get("symbols")
    if isinstance(symbols, list) and symbols:
        return str(symbols[0]).upper()
    symbol = data.get("symbol")
    if isinstance(symbol, str) and symbol:
        return symbol.upper()
    for key in ("readings", "moves"):
        entries = data.get(key)
        if isinstance(entries, list) and entries and isinstance(entries[0], dict):
            candidate = entries[0].get("symbol")
            if isinstance(candidate, str) and candidate:
                return candidate.upper()
    return None


def resolve_alert_direction(data: dict) -> str | None:
    """Pure function: best-effort "up"/"down" implied direction for an
    AlertLog row's own `data` JSON. None whenever the alert made no
    directional claim (e.g. a volume-spike or regime-change alert) --
    never inferred beyond what `data` actually says."""
    if not isinstance(data, dict):
        return None
    direction = data.get("direction")
    if isinstance(direction, str):
        normalized = direction.lower()
        if normalized in _UP_ALIASES:
            return "up"
        if normalized in _DOWN_ALIASES:
            return "down"
    pct_change = data.get("pct_change")
    if isinstance(pct_change, int | float) and pct_change != 0:
        return "up" if pct_change > 0 else "down"
    return None


def grade_alert_outcome(
    reference_price: float,
    evaluated_price: float,
    implied_direction: str | None,
    significant_move_pct: float,
) -> dict:
    """Pure function: reference/evaluated price + this alert's own implied
    direction (if any) -> a grade. `direction_continued` stays None when
    `implied_direction` is None -- there is no directional claim to grade
    right or wrong. `significant_move` is the one grade every gradable
    alert gets, regardless of direction: did a real move of at least
    `significant_move_pct` happen afterward."""
    realized_move_pct = (
        100 * (evaluated_price - reference_price) / reference_price if reference_price else 0.0
    )
    significant_move = abs(realized_move_pct) >= significant_move_pct
    direction_continued = None
    if implied_direction is not None and realized_move_pct != 0:
        realized_direction = "up" if realized_move_pct > 0 else "down"
        direction_continued = realized_direction == implied_direction
    return {
        "realized_move_pct": round(realized_move_pct, 4),
        "significant_move": significant_move,
        "direction_continued": direction_continued,
    }


def _index_at_or_before(rows: list, target: datetime) -> int | None:
    """Pure function: the last index in a timestamp-ascending row list
    whose timestamp is <= target, or None if every row is after it."""
    idx = None
    for i, row in enumerate(rows):
        if row.timestamp <= target:
            idx = i
        else:
            break
    return idx


def _index_at_or_after(rows: list, target: datetime) -> int | None:
    """Pure function: the first index whose timestamp is >= target, or
    None if stored history doesn't reach that far yet."""
    for i, row in enumerate(rows):
        if row.timestamp >= target:
            return i
    return None


async def grade_alert_performance(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Grades every ungraded AlertLog row whose resolvable symbol has real
    synced history reaching `alert_grading_horizon_days` past
    `triggered_at`. Returns how many rows were graded this call. Never
    grades an alert twice (alert_log_id is unique on
    AlertPerformanceGrade) and never grades one with no resolvable
    symbol."""
    settings = get_settings()
    horizon_days = settings.alert_grading_horizon_days
    significant_move_pct = settings.alert_grading_significant_move_pct

    async with session_factory() as session:
        graded_ids = list(await session.scalars(select(AlertPerformanceGrade.alert_log_id)))
        query = select(AlertLog)
        if graded_ids:
            query = query.where(AlertLog.id.not_in(graded_ids))
        candidates = list(await session.scalars(query))
    if not candidates:
        return 0

    graded = 0
    series_cache: dict[str, list] = {}
    async with session_factory() as session:
        for log in candidates:
            symbol = resolve_alert_symbol(log.data)
            if symbol is None:
                continue
            config = find_symbol_config(symbol)
            if config is None:
                continue

            if symbol not in series_cache:
                series_cache[symbol] = await get_series(
                    session_factory, config.model, config.symbol, Timeframe.DAILY
                )
            rows = series_cache[symbol]
            if not rows:
                continue

            reference_idx = _index_at_or_before(rows, log.triggered_at)
            if reference_idx is None:
                continue
            evaluated_idx = _index_at_or_after(
                rows, log.triggered_at + timedelta(days=horizon_days)
            )
            if evaluated_idx is None:
                continue  # horizon hasn't elapsed in stored history yet

            reference_price = float(rows[reference_idx].close)
            evaluated_price = float(rows[evaluated_idx].close)
            if reference_price == 0:
                continue

            implied_direction = resolve_alert_direction(log.data)
            outcome = grade_alert_outcome(
                reference_price, evaluated_price, implied_direction, significant_move_pct
            )
            session.add(
                AlertPerformanceGrade(
                    alert_log_id=log.id,
                    alert_type=log.alert_type,
                    symbol=symbol,
                    triggered_at=log.triggered_at,
                    horizon_days=horizon_days,
                    reference_price=reference_price,
                    evaluated_price=evaluated_price,
                    realized_move_pct=outcome["realized_move_pct"],
                    significant_move=outcome["significant_move"],
                    implied_direction=implied_direction,
                    direction_continued=outcome["direction_continued"],
                )
            )
            graded += 1
        if graded:
            await session.commit()
    return graded


def _summarize(graded: list[AlertPerformanceGrade]) -> dict:
    """Pure function: a list of AlertPerformanceGrade rows -> the same
    aggregate shape summarize_alert_performance/summarize_by_alert_type
    both return. None fields (not zero) when there's nothing to average --
    "no data yet" is a real, displayable state, not a score."""
    total = len(graded)
    if total == 0:
        return {
            "graded_count": 0,
            "significant_move_rate_pct": None,
            "directional_alerts_count": 0,
            "direction_continued_rate_pct": None,
            "avg_abs_realized_move_pct": None,
        }
    significant = sum(1 for g in graded if g.significant_move)
    directional = [g for g in graded if g.direction_continued is not None]
    direction_correct = sum(1 for g in directional if g.direction_continued)
    avg_move = sum(abs(float(g.realized_move_pct)) for g in graded) / total
    return {
        "graded_count": total,
        "significant_move_rate_pct": round(100 * significant / total, 1),
        "directional_alerts_count": len(directional),
        "direction_continued_rate_pct": (
            round(100 * direction_correct / len(directional), 1) if directional else None
        ),
        "avg_abs_realized_move_pct": round(avg_move, 4),
    }


async def summarize_alert_performance(
    session_factory: async_sessionmaker[AsyncSession],
    alert_type: str | None = None,
    limit: int = 500,
) -> dict:
    """Real, measured alert hit-rate over graded AlertLog entries -- never
    simulated. `alert_type=None` summarizes across every graded alert."""
    query = select(AlertPerformanceGrade).order_by(AlertPerformanceGrade.graded_at.desc())
    if alert_type is not None:
        query = query.where(AlertPerformanceGrade.alert_type == alert_type)
    query = query.limit(limit)
    async with session_factory() as session:
        graded = list(await session.scalars(query))
    return {"alert_type": alert_type, **_summarize(graded)}


async def summarize_alert_performance_by_type(
    session_factory: async_sessionmaker[AsyncSession], limit: int = 2000
) -> list[dict]:
    """Same real measurements as summarize_alert_performance, grouped by
    `alert_type` -- one entry per alert type that has at least one graded
    row, sorted by graded volume descending (most-evaluated types first)."""
    query = select(AlertPerformanceGrade).order_by(AlertPerformanceGrade.graded_at.desc())
    query = query.limit(limit)
    async with session_factory() as session:
        graded = list(await session.scalars(query))

    by_type: dict[str, list[AlertPerformanceGrade]] = {}
    for row in graded:
        by_type.setdefault(row.alert_type, []).append(row)

    summaries = [
        {"alert_type": alert_type, **_summarize(rows)} for alert_type, rows in by_type.items()
    ]
    summaries.sort(key=lambda s: s["graded_count"], reverse=True)
    return summaries
