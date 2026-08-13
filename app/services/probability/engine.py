import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import ProbabilitySnapshot
from app.services.analysis.regime import reconstruct_regime_at
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe

logger = logging.getLogger(__name__)

_MIN_SAMPLE_SIZE = 8
_DEFAULT_BUCKET_WIDTH = 10.0
_QUANTILE_LEVELS: tuple[tuple[str, float], ...] = (
    ("p10_pct", 0.10),
    ("p25_pct", 0.25),
    ("p50_pct", 0.50),
    ("p75_pct", 0.75),
    ("p90_pct", 0.90),
)


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


def compute_forward_return_quantiles(matches: list[float]) -> dict[str, float] | None:
    """p10/p25/p50/p75/p90 of a set of realized forward returns (fractions,
    e.g. 0.03 for +3%) -- the actual empirical spread of outcomes behind
    `avg_forward_return_pct`'s single mean, linearly interpolated between
    the two nearest order statistics (the standard "type 7" percentile, no
    numpy dependency needed for five values). None (never guessed) when
    there's nothing to measure a spread over.
    """
    if not matches:
        return None
    ordered = sorted(matches)
    n = len(ordered)

    def _percentile(p: float) -> float:
        if n == 1:
            return ordered[0]
        idx = (n - 1) * p
        lower_idx = int(idx)
        upper_idx = min(lower_idx + 1, n - 1)
        frac = idx - lower_idx
        return ordered[lower_idx] + (ordered[upper_idx] - ordered[lower_idx]) * frac

    return {name: round(100 * _percentile(p), 4) for name, p in _QUANTILE_LEVELS}


def compute_rsi_probability(
    rsi_series: list[float | None],
    returns_series: list[float | None],
    reference_rsi: float,
    bucket_width: float = _DEFAULT_BUCKET_WIDTH,
    horizon: int = 1,
    min_sample_size: int = _MIN_SAMPLE_SIZE,
    regime_series: list[str | None] | None = None,
    reference_regime: str | None = None,
) -> dict | None:
    """Empirical probability of an up/down/flat forward move, conditioned on
    RSI having previously been within `bucket_width` of `reference_rsi`.

    When `regime_series` (one entry per `rsi_series`/`returns_series` index)
    and `reference_regime` are both given, the match set is additionally
    restricted to periods reconstructed as the same market regime -- e.g.
    "similar RSI, and it was also a BULL regime" rather than RSI alone. If
    that stricter sample is too small (`min_sample_size`), this honestly
    falls back to the RSI-only sample instead of returning None outright,
    and reports `regime_conditioned=False` so callers can tell the
    conditioning didn't actually take effect -- never silently claims
    regime-awareness it didn't have enough data to back up.

    Pure function over already-computed history -- returns None (never a
    guessed number) if there isn't enough matching history to be meaningful.
    """
    forward = compute_forward_returns(returns_series, horizon)
    half_width = bucket_width / 2
    lower, upper = reference_rsi - half_width, reference_rsi + half_width

    rsi_matches_idx = [
        i
        for i, (rsi, fwd) in enumerate(zip(rsi_series, forward))
        if rsi is not None and fwd is not None and lower <= rsi <= upper
    ]

    regime_conditioned = False
    match_idx = rsi_matches_idx
    if regime_series is not None and reference_regime is not None:
        regime_matches_idx = [
            i
            for i in rsi_matches_idx
            if i < len(regime_series) and regime_series[i] == reference_regime
        ]
        if len(regime_matches_idx) >= min_sample_size:
            match_idx = regime_matches_idx
            regime_conditioned = True

    matches = [forward[i] for i in match_idx]
    if len(matches) < min_sample_size:
        return None

    positive = sum(1 for r in matches if r > 0)
    negative = sum(1 for r in matches if r < 0)
    flat = len(matches) - positive - negative
    sample_size = len(matches)

    result = {
        "sample_size": sample_size,
        "prob_up_pct": round(100 * positive / sample_size),
        "prob_down_pct": round(100 * negative / sample_size),
        "prob_flat_pct": round(100 * flat / sample_size),
        "avg_forward_return_pct": round(100 * sum(matches) / sample_size, 4),
        "regime_conditioned": regime_conditioned,
        "reference_regime": reference_regime if regime_conditioned else None,
    }
    quantiles = compute_forward_return_quantiles(matches)
    if quantiles is not None:
        result.update(quantiles)
    else:
        result.update(dict.fromkeys(name for name, _ in _QUANTILE_LEVELS))
    return result


class ProbabilityEngine:
    """Computes and persists empirical, RSI-conditioned forward-return probabilities."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def compute_and_store(
        self,
        symbol: str,
        model: type,
        timeframe: Timeframe = Timeframe.DAILY,
        horizon: int = 1,
        regime_index: dict[str, dict] | None = None,
    ) -> ProbabilitySnapshot | None:
        """`regime_index` is optional and caller-provided (built once via
        `app.services.analysis.regime.build_regime_index`, e.g. by
        ForecastEngine) rather than built here on every call -- it requires
        fetching several other symbols' full history, so callers that need
        it across several horizons/symbols in one request build it once and
        share it, instead of paying that cost per call. Omitted entirely,
        this behaves exactly as before (RSI-only conditioning)."""
        rows = await get_series(self._session_factory, model, symbol, timeframe)
        if len(rows) < _MIN_SAMPLE_SIZE + horizon:
            return None

        rsi_series = [float(r.rsi) if r.rsi is not None else None for r in rows]
        returns_series = [float(r.return_pct) if r.return_pct is not None else None for r in rows]

        reference_rsi = rsi_series[-1]
        if reference_rsi is None:
            return None

        regime_series: list[str | None] | None = None
        reference_regime: str | None = None
        if regime_index is not None:
            reconstructed = [reconstruct_regime_at(regime_index, r.timestamp) for r in rows]
            regime_series = [r.value if r is not None else None for r in reconstructed]
            reference_regime = regime_series[-1]

        result = compute_rsi_probability(
            rsi_series,
            returns_series,
            reference_rsi,
            horizon=horizon,
            regime_series=regime_series,
            reference_regime=reference_regime,
        )
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
