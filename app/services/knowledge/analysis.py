"""Pure nearest-historical-analog search -- no I/O, unit-testable.

Finds past candles whose RSI/volatility most closely resemble a symbol's
current reading, using z-score normalized Euclidean distance. Deterministic
nearest-neighbor lookup over already-computed data, never a guess.
"""

from datetime import datetime


def mean_std(values: list[float | None]) -> tuple[float | None, float | None]:
    """Sample mean/stddev over the non-None values -- shared with
    app.services.probability.engine's volatility-conditioning (same
    z-score-normalization need, reused rather than duplicated)."""
    present = [v for v in values if v is not None]
    if len(present) < 2:
        return None, None
    mean = sum(present) / len(present)
    variance = sum((v - mean) ** 2 for v in present) / (len(present) - 1)
    return mean, variance**0.5


def find_similar_episodes(
    rsi_series: list[float | None],
    volatility_series: list[float | None],
    timestamps: list[datetime],
    current_rsi: float,
    current_volatility: float | None,
    k: int = 5,
    exclude_recent: int = 5,
    regime_series: list[str | None] | None = None,
    reference_regime: str | None = None,
) -> list[dict]:
    """When `regime_series` (one entry per index, same length as
    `rsi_series`) and `reference_regime` are both given, the candidate pool
    is restricted to periods reconstructed as the same market regime before
    ranking by RSI/volatility distance -- "similar RSI, and it also
    happened during a BULL regime" rather than RSI/volatility alone. If
    fewer than `k` candidates survive that filter, this honestly falls back
    to the full (regime-agnostic) pool rather than returning a thin or
    empty result, and marks every returned episode's `regime_conditioned`
    accordingly so callers can tell whether the conditioning actually took
    effect.
    """
    n = len(timestamps)
    rsi_mean, rsi_std = mean_std(rsi_series)
    vol_mean, vol_std = mean_std(volatility_series)
    if rsi_std in (None, 0):
        return []

    ref_rsi_z = (current_rsi - rsi_mean) / rsi_std
    ref_vol_z = (
        (current_volatility - vol_mean) / vol_std
        if current_volatility is not None and vol_std not in (None, 0)
        else None
    )

    cutoff = max(0, n - exclude_recent)
    candidates = []
    for i in range(cutoff):
        rsi, vol = rsi_series[i], volatility_series[i]
        if rsi is None:
            continue
        rsi_z = (rsi - rsi_mean) / rsi_std

        if ref_vol_z is not None and vol is not None and vol_std not in (None, 0):
            vol_z = (vol - vol_mean) / vol_std
            distance = ((rsi_z - ref_rsi_z) ** 2 + (vol_z - ref_vol_z) ** 2) ** 0.5
        else:
            distance = abs(rsi_z - ref_rsi_z)

        candidates.append(
            {
                "index": i,
                "timestamp": timestamps[i],
                "rsi": rsi,
                "volatility": vol,
                "distance": distance,
            }
        )

    candidates.sort(key=lambda c: c["distance"])

    regime_conditioned = False
    pool = candidates
    if regime_series is not None and reference_regime is not None:
        regime_pool = [c for c in candidates if regime_series[c["index"]] == reference_regime]
        if len(regime_pool) >= k:
            pool = regime_pool
            regime_conditioned = True

    for c in pool[:k]:
        c["regime_conditioned"] = regime_conditioned
    return pool[:k]
