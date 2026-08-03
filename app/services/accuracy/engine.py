"""Prediction Accuracy dashboard -- aggregates every already-graded
`PriceForecastSnapshot` row (computed by
`app.services.forecast.engine.grade_price_forecasts()`) into Daily/Weekly/
Monthly/Asset accuracy views plus an overall summary, so the self-learning
history this project already stores is visible as a trend, not just a flat
list.

No new grading logic lives here -- every row this reads already has its
`realized_price`/`error_pct`/`direction_correct`/`confidence_correct` filled
in by the grading job; this module only buckets and averages what's already
computed, never re-derives it."""

from collections import defaultdict
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import PriceForecastSnapshot


def _period_key(day: date, granularity: str) -> str:
    if granularity == "daily":
        return day.isoformat()
    if granularity == "weekly":
        iso_year, iso_week, _ = day.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if granularity == "monthly":
        return f"{day.year}-{day.month:02d}"
    raise ValueError(f"unknown granularity: {granularity}")


def _aggregate_stats(rows: list[PriceForecastSnapshot]) -> dict:
    """Pure function: real aggregate stats over a set of already-graded
    rows -- every field is None (not zero) when nothing graded backs it,
    never a fabricated average."""
    errors = [abs(float(r.error_pct)) for r in rows if r.error_pct is not None]
    direction_graded = [r.direction_correct for r in rows if r.direction_correct is not None]
    confidence_graded = [r.confidence_correct for r in rows if r.confidence_correct is not None]
    return {
        "evaluated_count": len(rows),
        "avg_abs_error_pct": round(sum(errors) / len(errors), 4) if errors else None,
        "direction_accuracy_pct": (
            round(100 * sum(direction_graded) / len(direction_graded), 2)
            if direction_graded
            else None
        ),
        "confidence_accuracy_pct": (
            round(100 * sum(confidence_graded) / len(confidence_graded), 2)
            if confidence_graded
            else None
        ),
    }


def bucket_accuracy(rows: list[PriceForecastSnapshot], granularity: str) -> list[dict]:
    """Pure function: groups already-graded rows by the calendar day/
    ISO-week/month of their real `evaluated_at` timestamp -- only periods
    with at least one real graded row ever appear, never a padded empty
    period."""
    buckets: dict[str, list[PriceForecastSnapshot]] = defaultdict(list)
    for row in rows:
        if row.evaluated_at is None:
            continue
        buckets[_period_key(row.evaluated_at.date(), granularity)].append(row)
    return [{"period": period, **_aggregate_stats(buckets[period])} for period in sorted(buckets)]


def summarize_by_asset(rows: list[PriceForecastSnapshot]) -> list[dict]:
    """Pure function: real per-symbol aggregate stats -- only symbols with
    at least one real graded forecast appear (today, typically BTC only,
    since that's the only symbol the scheduler grades; this generalizes
    honestly the moment more symbols are graded, with no code change)."""
    by_symbol: dict[str, list[PriceForecastSnapshot]] = defaultdict(list)
    for row in rows:
        if row.evaluated_at is None:
            continue
        by_symbol[row.symbol].append(row)
    return [
        {"symbol": symbol, **_aggregate_stats(by_symbol[symbol])} for symbol in sorted(by_symbol)
    ]


def overall_summary(rows: list[PriceForecastSnapshot]) -> dict:
    graded = [r for r in rows if r.evaluated_at is not None]
    return _aggregate_stats(graded)


class AccuracyEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def _graded_rows(self, symbol: str | None = None) -> list[PriceForecastSnapshot]:
        async with self._session_factory() as session:
            query = select(PriceForecastSnapshot).where(
                PriceForecastSnapshot.evaluated_at.is_not(None)
            )
            if symbol is not None:
                query = query.where(PriceForecastSnapshot.symbol == symbol.upper())
            result = await session.scalars(
                query.order_by(PriceForecastSnapshot.evaluated_at.desc())
            )
            return list(result)

    async def compute(self, symbol: str | None = None, recent_limit: int = 50) -> dict:
        rows = await self._graded_rows(symbol)
        return {
            "symbol": symbol.upper() if symbol else None,
            "overall": overall_summary(rows),
            "daily": bucket_accuracy(rows, "daily"),
            "weekly": bucket_accuracy(rows, "weekly"),
            "monthly": bucket_accuracy(rows, "monthly"),
            "by_asset": summarize_by_asset(rows),
            "recent": [
                {
                    "symbol": r.symbol,
                    "horizon": r.horizon,
                    "computed_at": r.computed_at.isoformat(),
                    "evaluated_at": r.evaluated_at.isoformat(),
                    "target_price": float(r.target_price),
                    "realized_price": float(r.realized_price)
                    if r.realized_price is not None
                    else None,
                    "error_pct": float(r.error_pct) if r.error_pct is not None else None,
                    "direction_correct": r.direction_correct,
                    "confidence_correct": r.confidence_correct,
                    "confidence_tier": r.confidence_tier,
                }
                for r in rows[:recent_limit]
            ],
        }


def build_accuracy_engine() -> AccuracyEngine:
    from app.database.session import get_session_factory

    return AccuracyEngine(get_session_factory())
