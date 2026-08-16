"""Statistical significance helpers -- confidence intervals for the
proportion and mean-return statistics scattered across quality/learning/
alert_performance/trade_setup, so a bare accuracy_pct or win_rate_pct is
never presented as settled fact without its own sample-size-driven
uncertainty (POST-V9 Phase 15: "нельзя заявлять improvement 52% vs 51%
без sample size/uncertainty"). This is genuinely new capability -- no
bootstrap/confidence-interval code existed anywhere in this codebase
before this module; kept in one shared place so it's not reimplemented in
each of those four engines separately.

Two distinct cases, because a single formula can't honestly cover both:
  - `compute_wilson_interval` for a binomial proportion (accuracy_pct,
    win_rate_pct, hit_rate_pct, direction_continued_rate_pct) -- a proper
    small-sample interval, unlike the naive normal-approximation interval
    which can produce nonsensical bounds outside [0, 100] at low N.
  - `compute_bootstrap_ci` for the mean of a non-binary sample
    (mean_return_pct, expectancy_pct, avg_edge_vs_baseline_pct) -- reuses
    the exact resample-with-replacement pattern
    app.services.backtest.strategy.monte_carlo_simulation already proved
    out for equity-curve bootstrapping, applied here to a scalar mean.
"""

import random

# Two-sided 95% normal quantile (z-score) -- the standard default for a
# "95% confidence interval" claim.
_Z_95 = 1.959963984540054


def compute_wilson_interval(successes: int, total: int, z: float = _Z_95) -> dict | None:
    """Wilson score confidence interval for a binomial proportion. None
    (never a guessed interval) when there are no observations to bound."""
    if total <= 0:
        return None
    p = successes / total
    denominator = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denominator
    margin = (z * ((p * (1 - p) / total + z**2 / (4 * total**2)) ** 0.5)) / denominator
    return {
        "point_estimate_pct": round(100 * p, 2),
        "lower_pct": round(100 * max(0.0, center - margin), 2),
        "upper_pct": round(100 * min(1.0, center + margin), 2),
        "sample_count": total,
    }


def compute_bootstrap_ci(
    values: list[float],
    n_resamples: int = 1000,
    confidence: float = 0.95,
    seed: int | None = None,
) -> dict | None:
    """Percentile-bootstrap confidence interval for the mean of `values`.
    None below 2 samples, where a bootstrap distribution over resamples of
    a single point is meaningless (every resample is identical)."""
    n = len(values)
    if n < 2:
        return None
    rng = random.Random(seed)
    means = []
    for _ in range(n_resamples):
        resample = rng.choices(values, k=n)
        means.append(sum(resample) / n)
    means.sort()
    tail = (1 - confidence) / 2
    lower_idx = max(0, int(tail * n_resamples))
    upper_idx = min(n_resamples - 1, int((1 - tail) * n_resamples))
    return {
        "point_estimate": round(sum(values) / n, 4),
        "lower": round(means[lower_idx], 4),
        "upper": round(means[upper_idx], 4),
        "sample_count": n,
        "n_resamples": n_resamples,
    }
