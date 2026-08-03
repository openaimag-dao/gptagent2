import logging
from datetime import UTC, datetime, timedelta

import numpy as np
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Correlation

logger = logging.getLogger(__name__)

DEFAULT_WINDOWS_DAYS: tuple[int, ...] = (7, 14, 30, 90)

# (symbol_a, symbol_b) pairs required by the spec.
DEFAULT_PAIRS: tuple[tuple[str, str], ...] = (
    ("BTC", "NASDAQ"),
    ("BTC", "DXY"),
    ("BTC", "GOLD"),
    ("BTC", "VIX"),
    ("BTC", "US10Y"),
    ("BTC", "SPX"),
    ("ETH", "BTC"),
    ("SOL", "BTC"),
)

_MIN_COMMON_DATES = 4  # need at least 3 daily returns to call a correlation meaningful


def compute_correlation(
    closes_a: dict[str, float], closes_b: dict[str, float]
) -> tuple[float, int] | None:
    """Pearson correlation of daily % returns, aligned by calendar date.

    Returns (correlation, sample_size) or None if there isn't enough
    overlapping history to compute a meaningful value. Pure function --
    unit-testable without a database.
    """
    common_dates = sorted(set(closes_a) & set(closes_b))
    if len(common_dates) < _MIN_COMMON_DATES:
        return None

    prices_a = [closes_a[d] for d in common_dates]
    prices_b = [closes_b[d] for d in common_dates]

    returns_a = [(prices_a[i] - prices_a[i - 1]) / prices_a[i - 1] for i in range(1, len(prices_a))]
    returns_b = [(prices_b[i] - prices_b[i - 1]) / prices_b[i - 1] for i in range(1, len(prices_b))]

    if len(returns_a) < _MIN_COMMON_DATES - 1 or np.std(returns_a) == 0 or np.std(returns_b) == 0:
        return None

    correlation = float(np.corrcoef(returns_a, returns_b)[0, 1])
    if np.isnan(correlation):
        return None

    return correlation, len(returns_a)


def compute_correlation_strength(
    correlations: list[Correlation], window_days: int = 30
) -> int | None:
    """Pure function: a 0-100 "how correlated is everything right now" read
    -- the average absolute Pearson correlation across every real pair this
    project already tracks (`DEFAULT_PAIRS`) at the given window. Reuses the
    exact correlation values `CorrelationEngine.compute_and_store` already
    persisted -- no new pairwise computation. High = markets moving in
    lockstep (diversification offers little protection); low = markets
    decoupled. None (not fabricated) when no correlation has been computed
    yet at this window."""
    matches = [abs(float(c.correlation)) for c in correlations if c.window_days == window_days]
    if not matches:
        return None
    return round(min(100.0, (sum(matches) / len(matches)) * 100))


async def _daily_closes(session: AsyncSession, symbol: str, since: datetime) -> dict[str, float]:
    """One price per UTC calendar day: the last observation recorded that day."""
    query = text(
        """
        SELECT DISTINCT ON (date_trunc('day', recorded_at))
            date_trunc('day', recorded_at) AS day, price
        FROM asset_prices
        WHERE symbol = :symbol AND recorded_at >= :since
        ORDER BY date_trunc('day', recorded_at), recorded_at DESC
        """
    )
    result = await session.execute(query, {"symbol": symbol, "since": since})
    return {row.day.date().isoformat(): float(row.price) for row in result}


class CorrelationEngine:
    """Computes and persists rolling correlations across the configured pairs/windows."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        pairs: tuple[tuple[str, str], ...] = DEFAULT_PAIRS,
        windows_days: tuple[int, ...] = DEFAULT_WINDOWS_DAYS,
    ) -> None:
        self._session_factory = session_factory
        self._pairs = pairs
        self._windows_days = windows_days

    async def compute_and_store(self) -> list[Correlation]:
        stored: list[Correlation] = []

        async with self._session_factory() as session:
            closes_cache: dict[tuple[str, int], dict[str, float]] = {}

            for symbol_a, symbol_b in self._pairs:
                for window_days in self._windows_days:
                    since = datetime.now(UTC) - timedelta(days=window_days + 1)

                    # No try/except here on purpose: _daily_closes only raises for
                    # genuine infrastructure failures (DB unreachable, bad query) --
                    # missing/insufficient price data is handled gracefully by
                    # returning {} / None, never by raising. A real exception means
                    # every remaining pair/window will fail identically, so let it
                    # propagate once to the caller (scheduler/jobs.py) rather than
                    # logging the same traceback dozens of times in this loop.
                    for symbol in (symbol_a, symbol_b):
                        key = (symbol, window_days)
                        if key not in closes_cache:
                            closes_cache[key] = await _daily_closes(session, symbol, since)

                    result = compute_correlation(
                        closes_cache[(symbol_a, window_days)],
                        closes_cache[(symbol_b, window_days)],
                    )

                    if result is None:
                        continue

                    correlation, data_points = result
                    row = Correlation(
                        symbol_a=symbol_a,
                        symbol_b=symbol_b,
                        window_days=window_days,
                        correlation=correlation,
                        data_points=data_points,
                    )
                    session.add(row)
                    stored.append(row)

            await session.commit()

        return stored

    async def get_latest(self) -> list[Correlation]:
        async with self._session_factory() as session:
            latest: list[Correlation] = []
            for symbol_a, symbol_b in self._pairs:
                for window_days in self._windows_days:
                    row = await session.scalar(
                        select(Correlation)
                        .where(
                            Correlation.symbol_a == symbol_a,
                            Correlation.symbol_b == symbol_b,
                            Correlation.window_days == window_days,
                        )
                        .order_by(Correlation.calculated_at.desc())
                        .limit(1)
                    )
                    if row is not None:
                        latest.append(row)
            return latest
