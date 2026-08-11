"""Pure trade-return statistics -- no I/O, unit-testable.

All functions take a list of realized returns (fractions, e.g. 0.02 = +2%)
produced by a rule firing historically, and return the standard backtest
metrics. Every function returns None rather than a fabricated number when
the input can't support a meaningful answer (no trades, one trade for
Sharpe, no losing trades for profit factor).
"""


def compute_win_rate_pct(returns: list[float]) -> float | None:
    if not returns:
        return None
    wins = sum(1 for r in returns if r > 0)
    return round(100 * wins / len(returns), 2)


def compute_avg_return_pct(returns: list[float]) -> float | None:
    if not returns:
        return None
    return round(100 * sum(returns) / len(returns), 4)


def compute_max_drawdown_pct(returns: list[float]) -> float | None:
    """Max peak-to-trough drawdown of the equity curve formed by compounding
    these returns in sequence (as if each trade were taken one after another)."""
    if not returns:
        return None
    equity = 1.0
    peak = 1.0
    max_dd = 0.0
    for r in returns:
        equity *= 1 + r
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak)
    return round(100 * max_dd, 2)


def compute_profit_factor(returns: list[float]) -> float | None:
    """Gross gains / gross losses. None (not infinity, to stay JSON-safe) when
    there are no losing trades to divide by."""
    if not returns:
        return None
    gains = sum(r for r in returns if r > 0)
    losses = -sum(r for r in returns if r < 0)
    if losses == 0:
        return None
    return round(gains / losses, 3)


def compute_sharpe_ratio(returns: list[float], periods_per_year: int = 252) -> float | None:
    """Annualized Sharpe ratio (zero risk-free rate). None below 2 samples or
    zero variance, where the ratio is undefined."""
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    variance = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    std = variance**0.5
    if std == 0:
        return None
    return round((mean / std) * (periods_per_year**0.5), 3)


def compute_sortino_ratio(returns: list[float], periods_per_year: int = 252) -> float | None:
    """Same annualization as compute_sharpe_ratio, but only penalizes
    downside variance (returns below 0) rather than total variance. None
    below 2 samples or when there are no losing trades, where downside
    deviation is undefined."""
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    downside = [min(r, 0.0) ** 2 for r in returns]
    downside_deviation = (sum(downside) / len(returns)) ** 0.5
    if downside_deviation == 0:
        return None
    return round((mean / downside_deviation) * (periods_per_year**0.5), 3)


def compute_calmar_ratio(returns: list[float], periods_per_year: int = 252) -> float | None:
    """Annualized mean return (same mean*periods_per_year assumption
    compute_sharpe_ratio's annualization implies) divided by the max
    drawdown of the compounded equity curve. None when there's no drawdown
    to divide by (an all-gains run) or no returns."""
    if not returns:
        return None
    max_dd_pct = compute_max_drawdown_pct(returns)
    if not max_dd_pct:
        return None
    mean = sum(returns) / len(returns)
    annualized_return_pct = 100 * mean * periods_per_year
    return round(annualized_return_pct / max_dd_pct, 3)


def compute_cagr_pct(returns: list[float], periods_per_year: int = 252) -> float | None:
    """Compounded return across all occurrences, annualized by treating each
    occurrence as one "period" out of periods_per_year -- the same per-period
    assumption compute_sharpe_ratio already makes via its sqrt(periods_per_year)
    scaling, applied here to the equity curve instead of the mean/std. Not a
    calendar-time CAGR (occurrences aren't evenly spaced in time); this is an
    occurrence-annualized total return, consistent with how the rest of this
    module already treats the trade sequence as the compounding unit."""
    if not returns:
        return None
    equity = 1.0
    for r in returns:
        equity *= 1 + r
    if equity <= 0:
        return None
    return round(100 * (equity ** (periods_per_year / len(returns)) - 1), 3)


def compute_var_pct(returns: list[float], confidence: float = 0.95) -> float | None:
    """Historical (non-parametric) Value at Risk: the loss at the given
    confidence percentile of the empirical return distribution. Returned as
    a positive percentage (magnitude of the loss). None below 2 samples."""
    if len(returns) < 2:
        return None
    ordered = sorted(returns)
    index = int((1 - confidence) * len(ordered))
    index = min(index, len(ordered) - 1)
    return round(-100 * ordered[index], 3)


def compute_cvar_pct(returns: list[float], confidence: float = 0.95) -> float | None:
    """Historical Conditional VaR (Expected Shortfall): the average return
    among the worst (1-confidence) tail of the empirical distribution.
    Returned as a positive percentage. None below 2 samples."""
    if len(returns) < 2:
        return None
    ordered = sorted(returns)
    cutoff = max(1, int((1 - confidence) * len(ordered)))
    tail = ordered[:cutoff]
    return round(-100 * sum(tail) / len(tail), 3)


def compute_expectancy_pct(returns: list[float]) -> float | None:
    """Average realized return per trade -- identical to compute_avg_return_pct
    but kept as its own named metric since "expectancy" is the standard term
    traders look for in a backtest report."""
    return compute_avg_return_pct(returns)


def compute_avg_win_pct(returns: list[float]) -> float | None:
    wins = [r for r in returns if r > 0]
    if not wins:
        return None
    return round(100 * sum(wins) / len(wins), 4)


def compute_avg_loss_pct(returns: list[float]) -> float | None:
    """Average magnitude of losing trades, as a positive percentage."""
    losses = [r for r in returns if r < 0]
    if not losses:
        return None
    return round(-100 * sum(losses) / len(losses), 4)


def apply_trading_costs(
    returns: list[float], fee_pct: float = 0.1, slippage_pct: float = 0.05
) -> list[float]:
    """Subtracts a documented, conservative round-trip trading cost from
    every trade return, replacing the previous implicit zero-cost fill
    assumption. Defaults: fee_pct=0.1 (roughly a 2x0.05% taker-fee round
    trip, e.g. Binance spot) + slippage_pct=0.05 (a conservative estimate
    for a liquid large-cap). These are documented assumptions, not measured
    values -- callers that know the actual venue/asset should override them."""
    cost = (fee_pct + slippage_pct) / 100
    return [r - cost for r in returns]


def compute_backtest_metrics(returns: list[float]) -> dict | None:
    if not returns:
        return None
    return {
        "occurrences": len(returns),
        "win_rate_pct": compute_win_rate_pct(returns),
        "avg_return_pct": compute_avg_return_pct(returns),
        "max_drawdown_pct": compute_max_drawdown_pct(returns),
        "profit_factor": compute_profit_factor(returns),
        "sharpe_ratio": compute_sharpe_ratio(returns),
        "sortino_ratio": compute_sortino_ratio(returns),
        "calmar_ratio": compute_calmar_ratio(returns),
        "cagr_pct": compute_cagr_pct(returns),
        "var_95_pct": compute_var_pct(returns),
        "cvar_95_pct": compute_cvar_pct(returns),
        "expectancy_pct": compute_expectancy_pct(returns),
        "avg_win_pct": compute_avg_win_pct(returns),
        "avg_loss_pct": compute_avg_loss_pct(returns),
    }
