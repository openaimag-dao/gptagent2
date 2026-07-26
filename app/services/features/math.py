"""Pure feature-computation functions -- no I/O, unit-testable. Every
function returns None rather than a fabricated number when the input can't
support a meaningful answer, matching app/services/backtest/metrics.py.
"""


def compute_returns(closes: list[float]) -> list[float]:
    """Simple period-over-period returns, one shorter than `closes`."""
    return [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] != 0
    ]


def compute_rolling_momentum(closes: list[float], window: int) -> float | None:
    """Percent change over the last `window` closes."""
    if len(closes) <= window or closes[-1 - window] == 0:
        return None
    return round(100 * (closes[-1] - closes[-1 - window]) / closes[-1 - window], 4)


def compute_beta(asset_returns: list[float], benchmark_returns: list[float]) -> float | None:
    """Beta of asset vs benchmark: cov(asset, benchmark) / var(benchmark).
    Requires equal-length, paired return series with at least 2 points and
    nonzero benchmark variance."""
    n = min(len(asset_returns), len(benchmark_returns))
    if n < 2:
        return None
    a = asset_returns[-n:]
    b = benchmark_returns[-n:]
    mean_a = sum(a) / n
    mean_b = sum(b) / n
    covariance = sum((a[i] - mean_a) * (b[i] - mean_b) for i in range(n)) / (n - 1)
    variance_b = sum((x - mean_b) ** 2 for x in b) / (n - 1)
    if variance_b == 0:
        return None
    return round(covariance / variance_b, 4)


def compute_market_breadth(changes_pct: list[float]) -> float | None:
    """Percent of symbols with a positive change -- a simple advance/decline
    breadth reading over whatever universe is passed in."""
    if not changes_pct:
        return None
    advancing = sum(1 for c in changes_pct if c > 0)
    return round(100 * advancing / len(changes_pct), 2)


def _ols_slope_intercept(x: list[float], y: list[float]) -> tuple[float, float] | None:
    n = len(x)
    if n < 2:
        return None
    mean_x = sum(x) / n
    mean_y = sum(y) / n
    denom = sum((xi - mean_x) ** 2 for xi in x)
    if denom == 0:
        return None
    slope = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n)) / denom
    intercept = mean_y - slope * mean_x
    return slope, intercept


def dickey_fuller_test(series: list[float]) -> dict | None:
    """A basic (non-augmented, no lag terms) Dickey-Fuller unit-root test:
    regresses delta(y_t) on y_{t-1} (with a constant) and t-tests the slope
    against 0. Slope significantly negative => reject the unit-root null =>
    series looks stationary. Uses MacKinnon's ~-2.86 asymptotic 5% critical
    value for the constant-only case -- an approximation, not a full ADF
    with augmenting lag terms (this project has no statsmodels dependency).
    Returns None below 3 points or if the regression is degenerate.
    """
    if len(series) < 3:
        return None
    y_lag = series[:-1]
    delta_y = [series[i] - series[i - 1] for i in range(1, len(series))]
    fit = _ols_slope_intercept(y_lag, delta_y)
    if fit is None:
        return None
    slope, intercept = fit

    n = len(y_lag)
    if n <= 2:
        return None
    mean_x = sum(y_lag) / n
    denom = sum((x - mean_x) ** 2 for x in y_lag)
    if denom == 0:
        return None

    residuals = [delta_y[i] - (intercept + slope * y_lag[i]) for i in range(n)]
    residual_variance = sum(r**2 for r in residuals) / (n - 2)
    if residual_variance == 0:
        # Perfect fit -- unambiguous (not a division-by-zero problem to hide
        # behind None): a strictly negative slope means the series snaps
        # back to its mean every single step, about as stationary as it gets.
        statistic = -999.0 if slope < 0 else 999.0
    else:
        se_slope = (residual_variance / denom) ** 0.5
        statistic = slope / se_slope
    return {"statistic": round(statistic, 4), "is_stationary": statistic < -2.86}


def compute_cointegration(series_a: list[float], series_b: list[float]) -> dict | None:
    """Engle-Granger two-step cointegration test: OLS-regress `series_a` on
    `series_b` to get a hedge ratio, form the spread (residuals), then run
    the Dickey-Fuller test above on that spread. A stationary spread means
    the two series don't wander apart indefinitely -- the textbook
    definition of cointegration."""
    n = min(len(series_a), len(series_b))
    if n < 5:
        return None
    a = series_a[-n:]
    b = series_b[-n:]
    fit = _ols_slope_intercept(b, a)
    if fit is None:
        return None
    hedge_ratio, intercept = fit
    spread = [a[i] - (intercept + hedge_ratio * b[i]) for i in range(n)]
    df = dickey_fuller_test(spread)
    if df is None:
        return None
    return {"hedge_ratio": round(hedge_ratio, 6), "spread": spread, **df}


def compute_momentum_delta(values: list[float]) -> float | None:
    """Change between the first and last value of a short series -- used
    for funding-rate momentum and open-interest change, both derived from
    the persisted WhaleSnapshot history rather than a live-only reading."""
    if len(values) < 2 or values[0] == 0:
        return None
    return round(100 * (values[-1] - values[0]) / abs(values[0]), 4)
