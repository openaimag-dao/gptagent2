import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import ProbabilitySnapshot
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe

logger = logging.getLogger(__name__)

_MIN_SAMPLE_SIZE = 8
_DEFAULT_BUCKET_WIDTH = 10.0


def compute_forward_returns(returns: list[float | None], horizon: int = 1) -> list[float | None]:
    """Real cumulative (compounded) return over the next `horizon` periods
    after candle i -- what an investor would have actually realized holding
    from i to i+horizon, not just the single period's return that happens to
    land exactly `horizon` periods later. For horizon=1 this is identical to
    the single-period return (compounding one term is a no-op), which is why
    the bug this replaces (naively indexing `returns[i + horizon]` instead of
    compounding every period in between) only ever showed up for horizon>1 --
    it silently understated 3d/7d/30d-style forward moves to roughly
    single-day magnitude. None when any period in the window is missing or
    the window runs past the end of the series (never silently skips a gap
    or guesses)."""
    n = len(returns)
    result: list[float | None] = []
    for i in range(n):
        window = returns[i + 1 : i + 1 + horizon]
        if len(window) < horizon or any(r is None for r in window):
            result.append(None)
            continue
        cumulative = 1.0
        for r in window:
            cumulative *= 1 + r
        result.append(cumulative - 1)
    return result


def compute_rsi_probability(
    rsi_series: list[float | None],
    returns_series: list[float | None],
    reference_rsi: float,
    bucket_width: float = _DEFAULT_BUCKET_WIDTH,
    horizon: int = 1,
    min_sample_size: int = _MIN_SAMPLE_SIZE,
) -> dict | None:
    """Empirical probability of an up/down/flat forward move, conditioned on
    RSI having previously been within `bucket_width` of `reference_rsi`.

    Pure function over already-computed history -- returns None (never a
    guessed number) if there isn't enough matching history to be meaningful.
    """
    forward = compute_forward_returns(returns_series, horizon)
    half_width = bucket_width / 2
    lower, upper = reference_rsi - half_width, reference_rsi + half_width

    matches = [
        fwd
        for rsi, fwd in zip(rsi_series, forward)
        if rsi is not None and fwd is not None and lower <= rsi <= upper
    ]
    if len(matches) < min_sample_size:
        return None

    positive = sum(1 for r in matches if r > 0)
    negative = sum(1 for r in matches if r < 0)
    flat = len(matches) - positive - negative
    sample_size = len(matches)

    return {
        "sample_size": sample_size,
        "prob_up_pct": round(100 * positive / sample_size),
        "prob_down_pct": round(100 * negative / sample_size),
        "prob_flat_pct": round(100 * flat / sample_size),
        "avg_forward_return_pct": round(100 * sum(matches) / sample_size, 4),
    }


class ProbabilityEngine:
    """Computes and persists empirical, RSI-conditioned forward-return probabilities."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def compute_and_store(
        self, symbol: str, model: type, timeframe: Timeframe = Timeframe.DAILY, horizon: int = 1
    ) -> ProbabilitySnapshot | None:
        rows = await get_series(self._session_factory, model, symbol, timeframe)
        if len(rows) < _MIN_SAMPLE_SIZE + horizon:
            return None

        rsi_series = [float(r.rsi) if r.rsi is not None else None for r in rows]
        returns_series = [float(r.return_pct) if r.return_pct is not None else None for r in rows]

        reference_rsi = rsi_series[-1]
        if reference_rsi is None:
            return None

        result = compute_rsi_probability(rsi_series, returns_series, reference_rsi, horizon=horizon)
        if result is None:
            return None

        snapshot = ProbabilitySnapshot(
            symbol=symbol,
            timeframe=timeframe.value,
            horizon_periods=horizon,
            reference_rsi=reference_rsi,
            reference_timestamp=rows[-1].timestamp,
            **result,
        )
        async with self._session_factory() as session:
            session.add(snapshot)
            await session.commit()
            await session.refresh(snapshot)
        return snapshot

    async def get_latest(
        self, symbol: str, timeframe: Timeframe = Timeframe.DAILY, horizon: int | None = None
    ) -> ProbabilitySnapshot | None:
        async with self._session_factory() as session:
            conditions = [
                ProbabilitySnapshot.symbol == symbol,
                ProbabilitySnapshot.timeframe == timeframe.value,
            ]
            if horizon is not None:
                conditions.append(ProbabilitySnapshot.horizon_periods == horizon)
            return await session.scalar(
                select(ProbabilitySnapshot)
                .where(*conditions)
                .order_by(ProbabilitySnapshot.computed_at.desc())
                .limit(1)
            )


def label_probability(snapshot: ProbabilitySnapshot) -> dict:
    """Bullish/Bearish/Neutral framing over the same up/down/flat numbers --
    a presentation alias, not a second model."""
    return {
        "bullish_pct": snapshot.prob_up_pct,
        "bearish_pct": snapshot.prob_down_pct,
        "neutral_pct": snapshot.prob_flat_pct,
    }


def contributing_indicators(signal_factors: dict[str, dict]) -> list[dict]:
    """Which Signal Engine factors actually fired, for "why this probability"
    context -- reuses the existing factor breakdown rather than a second
    indicator model."""
    return [
        {"indicator": name, "points": data.get("points"), "triggered": data.get("triggered")}
        for name, data in signal_factors.items()
        if data.get("triggered") is not None
    ]
