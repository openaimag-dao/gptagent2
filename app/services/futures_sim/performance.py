"""Futures Simulator -- performance analytics. Pure functions over a list
of closed FuturesSimTrade rows, zero I/O (the API layer does the query and
hands the results in) -- reuses app.services.backtest.metrics rather than
building a parallel metrics engine (task's own anti-duplication mandate).

Every compute_backtest_metrics() ratio (Sharpe, Sortino, max drawdown,
profit factor, ...) is fed each trade's ROI-on-margin (roi_pct / 100) as
its "return" -- the same equity-curve-over-a-return-sequence model
app.services.backtest.metrics already assumes, applied here to demo
trades instead of backtested signal fires."""

from app.database.models import FuturesSimTrade
from app.services.backtest.metrics import compute_backtest_metrics


def _trade_stats(trades: list[FuturesSimTrade]) -> dict:
    """Aggregate stats for one group of trades (task: Total Trades/
    Winning/Losing/Win Rate/Profit Factor/Avg Win/Avg Loss/Expectancy/
    Total PnL/Total Fees/Total Funding/Max Drawdown/Sharpe/Sortino)."""
    total_trades = len(trades)
    winning_trades = sum(1 for t in trades if float(t.net_pnl) > 0)
    losing_trades = sum(1 for t in trades if float(t.net_pnl) < 0)
    total_pnl = sum(float(t.net_pnl) for t in trades)
    total_fees = sum(float(t.fees) for t in trades)
    total_funding = sum(float(t.funding) for t in trades)
    liquidations = sum(1 for t in trades if t.exit_reason == "LIQUIDATION")

    returns = [float(t.roi_pct) / 100 for t in trades]
    metrics = compute_backtest_metrics(returns) or {}

    return {
        "total_trades": total_trades,
        "winning_trades": winning_trades,
        "losing_trades": losing_trades,
        "win_rate_pct": metrics.get("win_rate_pct"),
        "profit_factor": metrics.get("profit_factor"),
        "avg_win_pct": metrics.get("avg_win_pct"),
        "avg_loss_pct": metrics.get("avg_loss_pct"),
        "expectancy_pct": metrics.get("expectancy_pct"),
        "total_pnl": round(total_pnl, 8),
        "total_fees": round(total_fees, 8),
        "total_funding": round(total_funding, 8),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "sharpe_ratio": metrics.get("sharpe_ratio"),
        "sortino_ratio": metrics.get("sortino_ratio"),
        "liquidations": liquidations,
    }


def compute_performance_stats(trades: list[FuturesSimTrade]) -> dict:
    """Task: Performance Analytics, broken down by Long/Short, by symbol,
    by leverage (task's own "Leverage Performance breakdown"), and by
    strategy tag (manual vs ai_assisted -- task's AI vs User Performance
    comparison). Every breakdown is the same _trade_stats() shape as
    `overall`, just filtered to that slice of trades."""
    by_side = {
        side: _trade_stats([t for t in trades if t.side == side])
        for side in ("LONG", "SHORT")
        if any(t.side == side for t in trades)
    }
    by_symbol = {
        symbol: _trade_stats([t for t in trades if t.symbol == symbol])
        for symbol in sorted({t.symbol for t in trades})
    }
    by_leverage = {
        str(leverage): _trade_stats([t for t in trades if t.leverage == leverage])
        for leverage in sorted({t.leverage for t in trades})
    }
    by_strategy = {
        tag: _trade_stats([t for t in trades if t.strategy_tag == tag])
        for tag in sorted({t.strategy_tag for t in trades})
    }

    return {
        "overall": _trade_stats(trades),
        "by_side": by_side,
        "by_symbol": by_symbol,
        "by_leverage": by_leverage,
        "by_strategy": by_strategy,
    }
