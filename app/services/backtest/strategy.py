"""Pure Strategy Lab math -- no I/O. Extends the Backtest Engine's
condition-firing model (app/services/backtest/engine.py, conditions.py,
metrics.py, all reused as-is) with early exits (stop-loss/take-profit) and
Monte Carlo resampling. Position sizing scales `metrics.py`'s equity-curve
math (already used for max-drawdown) rather than reimplementing it.
"""

import random


def simulate_trade_exit(
    future_returns: list[float],
    stop_loss_pct: float | None = None,
    take_profit_pct: float | None = None,
) -> float | None:
    """Compounds `future_returns` (sequential single-period returns
    starting the day after entry) day by day, exiting as soon as the
    cumulative return crosses -stop_loss_pct or +take_profit_pct. Returns
    the realized return at exit, or the full-horizon cumulative return if
    neither triggers. None for an empty input (nothing to simulate)."""
    if not future_returns:
        return None
    equity = 1.0
    for r in future_returns:
        equity *= 1 + r
        cumulative = equity - 1.0
        if stop_loss_pct is not None and cumulative <= -abs(stop_loss_pct):
            return -abs(stop_loss_pct)
        if take_profit_pct is not None and cumulative >= abs(take_profit_pct):
            return abs(take_profit_pct)
    return equity - 1.0


def apply_position_size(trade_return: float, position_size_pct: float) -> float:
    """Scales a trade's return by the fraction of capital actually risked
    -- a 10% move at 50% position size contributes 5% to the portfolio."""
    return trade_return * position_size_pct


def _percentile(sorted_values: list[float], p: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    idx = round(p / 100 * (len(sorted_values) - 1))
    return sorted_values[idx]


def monte_carlo_simulation(
    trade_returns: list[float],
    n_simulations: int = 1000,
    trades_per_sim: int | None = None,
    seed: int | None = None,
) -> dict | None:
    """Bootstrap-resamples the REAL historical trade returns (with
    replacement) to build a distribution of possible equity-curve outcomes
    -- never invents a return that didn't actually occur, only resamples
    the order/combination in which the real ones could have landed.
    Returns 5th/50th/95th percentile total return and max drawdown, or None
    with fewer than 2 historical trades (nothing meaningful to resample)."""
    if len(trade_returns) < 2:
        return None
    trades_per_sim = trades_per_sim or len(trade_returns)
    rng = random.Random(seed)

    total_returns: list[float] = []
    max_drawdowns: list[float] = []
    for _ in range(n_simulations):
        sample = [rng.choice(trade_returns) for _ in range(trades_per_sim)]
        equity = 1.0
        peak = 1.0
        max_dd = 0.0
        for r in sample:
            equity *= 1 + r
            peak = max(peak, equity)
            if peak > 0:
                max_dd = max(max_dd, (peak - equity) / peak)
        total_returns.append(equity - 1.0)
        max_drawdowns.append(max_dd)

    total_returns.sort()
    max_drawdowns.sort()
    return {
        "n_simulations": n_simulations,
        "trades_per_sim": trades_per_sim,
        "total_return_p5_pct": round(100 * _percentile(total_returns, 5), 2),
        "total_return_p50_pct": round(100 * _percentile(total_returns, 50), 2),
        "total_return_p95_pct": round(100 * _percentile(total_returns, 95), 2),
        "max_drawdown_p50_pct": round(100 * _percentile(max_drawdowns, 50), 2),
        "max_drawdown_p95_pct": round(100 * _percentile(max_drawdowns, 95), 2),
    }
