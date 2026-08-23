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
    never a fabricated average.

    POST-V9 Phase 14: also reports the same two accuracy numbers for the
    naive baselines grade_price_forecasts() already computed alongside
    the real grading (momentum_baseline_correct/
    historical_mean_baseline_error_pct), plus explicit `beats_*` booleans
    -- a forecast is only "predictive edge" if it actually outperforms
    doing nothing clever, not merely non-random. `beats_random_walk`
    needs no baseline column at all: a random-walk direction call is 50%
    correct by construction, so it's a plain comparison against that
    constant."""
    errors = [abs(float(r.error_pct)) for r in rows if r.error_pct is not None]
    direction_graded = [r.direction_correct for r in rows if r.direction_correct is not None]
    confidence_graded = [r.confidence_correct for r in rows if r.confidence_correct is not None]
    momentum_graded = [
        r.momentum_baseline_correct for r in rows if r.momentum_baseline_correct is not None
    ]
    historical_mean_errors = [
        abs(float(r.historical_mean_baseline_error_pct))
        for r in rows
        if r.historical_mean_baseline_error_pct is not None
    ]
    zero_return_errors = [
        abs(float(r.zero_return_baseline_error_pct))
        for r in rows
        if r.zero_return_baseline_error_pct is not None
    ]
    regime_mean_errors = [
        abs(float(r.regime_mean_baseline_error_pct))
        for r in rows
        if r.regime_mean_baseline_error_pct is not None
    ]
    target_reached_graded = [r.target_reached for r in rows if r.target_reached is not None]

    avg_abs_error_pct = round(sum(errors) / len(errors), 4) if errors else None
    direction_accuracy_pct = (
        round(100 * sum(direction_graded) / len(direction_graded), 2) if direction_graded else None
    )
    momentum_baseline_accuracy_pct = (
        round(100 * sum(momentum_graded) / len(momentum_graded), 2) if momentum_graded else None
    )
    historical_mean_baseline_avg_abs_error_pct = (
        round(sum(historical_mean_errors) / len(historical_mean_errors), 4)
        if historical_mean_errors
        else None
    )
    zero_return_baseline_avg_abs_error_pct = (
        round(sum(zero_return_errors) / len(zero_return_errors), 4) if zero_return_errors else None
    )
    regime_mean_baseline_avg_abs_error_pct = (
        round(sum(regime_mean_errors) / len(regime_mean_errors), 4) if regime_mean_errors else None
    )

    return {
        "evaluated_count": len(rows),
        "avg_abs_error_pct": avg_abs_error_pct,
        "direction_accuracy_pct": direction_accuracy_pct,
        "confidence_accuracy_pct": (
            round(100 * sum(confidence_graded) / len(confidence_graded), 2)
            if confidence_graded
            else None
        ),
        "beats_random_walk": (
            direction_accuracy_pct > 50.0 if direction_accuracy_pct is not None else None
        ),
        "momentum_baseline_accuracy_pct": momentum_baseline_accuracy_pct,
        "beats_momentum_baseline": (
            direction_accuracy_pct > momentum_baseline_accuracy_pct
            if direction_accuracy_pct is not None and momentum_baseline_accuracy_pct is not None
            else None
        ),
        "historical_mean_baseline_avg_abs_error_pct": historical_mean_baseline_avg_abs_error_pct,
        "beats_historical_mean_baseline": (
            avg_abs_error_pct < historical_mean_baseline_avg_abs_error_pct
            if avg_abs_error_pct is not None
            and historical_mean_baseline_avg_abs_error_pct is not None
            else None
        ),
        "zero_return_baseline_avg_abs_error_pct": zero_return_baseline_avg_abs_error_pct,
        "beats_zero_return_baseline": (
            avg_abs_error_pct < zero_return_baseline_avg_abs_error_pct
            if avg_abs_error_pct is not None and zero_return_baseline_avg_abs_error_pct is not None
            else None
        ),
        "regime_mean_baseline_avg_abs_error_pct": regime_mean_baseline_avg_abs_error_pct,
        "beats_regime_mean_baseline": (
            avg_abs_error_pct < regime_mean_baseline_avg_abs_error_pct
            if avg_abs_error_pct is not None and regime_mean_baseline_avg_abs_error_pct is not None
            else None
        ),
        # Forecast Intelligence Upgrade: did price actually TOUCH the
        # stated target at any point during the window, not just end up
        # past it at horizon-elapse -- a materially different (and
        # usually higher) rate than direction_accuracy_pct.
        "target_hit_rate_pct": (
            round(100 * sum(target_reached_graded) / len(target_reached_graded), 2)
            if target_reached_graded
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


def summarize_by_regime_horizon(rows: list[PriceForecastSnapshot]) -> list[dict]:
    """Pure function: POST-V9 Phase 16 -- real accuracy stats broken down
    by the *combination* of regime and horizon, not just one dimension at
    a time (existing bucket_accuracy/summarize_by_asset only ever group
    on a single key). Reuses `regime_at_forecast` and `horizon`, both
    already persisted on every row (see PriceForecastSnapshot), so this
    is a pure regroup of data already fetched -- no new I/O, no new
    columns. A row with no recorded regime (forecasts computed before
    `regime_at_forecast` existed) is honestly excluded from the matrix
    rather than dumped into a fake "unknown" cell."""
    by_cell: dict[tuple[str, str], list[PriceForecastSnapshot]] = defaultdict(list)
    for row in rows:
        if row.evaluated_at is None or row.regime_at_forecast is None:
            continue
        by_cell[(row.regime_at_forecast, row.horizon)].append(row)
    return [
        {"regime": regime, "horizon": horizon, **_aggregate_stats(by_cell[(regime, horizon)])}
        for regime, horizon in sorted(by_cell)
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
            "by_regime_horizon": summarize_by_regime_horizon(rows),
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
                    "target_reached": r.target_reached,
                    "confidence_tier": r.confidence_tier,
                }
                for r in rows[:recent_limit]
            ],
        }


def build_accuracy_engine() -> AccuracyEngine:
    from app.database.session import get_session_factory

    return AccuracyEngine(get_session_factory())
