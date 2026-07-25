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
    }
