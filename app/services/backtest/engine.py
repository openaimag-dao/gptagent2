import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.backtest.conditions import Condition, evaluate_rule
from app.services.backtest.metrics import apply_trading_costs, compute_backtest_metrics
from app.services.history.registry import STOCK_TICKERS, find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.probability.engine import compute_forward_returns

logger = logging.getLogger(__name__)


def universe_caveat(target_symbol: str) -> str | None:
    """None for every symbol except this project's fixed 7-company equities
    roster, where it names the survivorship exposure: the roster is a
    present-day selection of still-successful mega-caps applied
    retroactively across all of history, so companies that failed or were
    delisted before qualifying are absent from every backtest result."""
    if target_symbol not in STOCK_TICKERS:
        return None
    return (
        "This symbol is one of a fixed, present-day-selected mega-cap roster "
        "(AAPL/MSFT/NVDA/TSLA/AMZN/META/GOOGL) applied retroactively across all of "
        "history -- companies that failed or were delisted before qualifying for "
        "that list are absent, so results should not be read as representative of "
        "'large caps in general' historically, only of these specific survivors."
    )


def _row_to_dict(row) -> dict:
    fields = (
        "close",
        "return_pct",
        "volatility",
        "atr",
        "rsi",
        "macd",
        "macd_signal",
        "macd_histogram",
        "sma_20",
        "sma_50",
        "sma_200",
        "volume_change_pct",
    )
    return {
        field: (float(v) if (v := getattr(row, field)) is not None else None) for field in fields
    }


class BacktestEngine:
    """Backtests a structured rule (AND of Conditions) over a symbol's full
    stored history: every date the rule's conditions all evaluate True, the
    target symbol's forward return over `horizon` periods becomes one trade.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def run(
        self,
        conditions: list[Condition],
        target_symbol: str,
        timeframe: Timeframe = Timeframe.DAILY,
        horizon: int = 1,
        fill_lag_periods: int = 1,
        fee_pct: float = 0.1,
        slippage_pct: float = 0.05,
    ) -> dict | None:
        """fill_lag_periods=1 (default) enters the trade at the close of the
        bar AFTER the one where the rule fired, not the same bar's own close
        -- a rule can only be confirmed once that bar's close is known, so
        filling at that same close assumes an impossible zero-latency,
        zero-slippage execution. fee_pct/slippage_pct are documented
        round-trip cost assumptions applied to every trade -- see
        apply_trading_costs. Set fill_lag_periods=0 only to reproduce the
        old (unrealistic) same-bar-fill behavior for comparison."""
        target_config = find_symbol_config(target_symbol)
        if target_config is None:
            return None

        symbols_needed = {c.symbol for c in conditions} | {target_symbol}
        series_by_symbol: dict[str, dict] = {}
        for symbol in symbols_needed:
            config = find_symbol_config(symbol)
            if config is None or timeframe not in config.timeframes:
                return None
            rows = await get_series(self._session_factory, config.model, symbol, timeframe)
            series_by_symbol[symbol] = {r.timestamp: _row_to_dict(r) for r in rows}

        target_rows = await get_series(
            self._session_factory, target_config.model, target_symbol, timeframe
        )
        if not target_rows:
            return None

        target_returns = [
            float(r.return_pct) if r.return_pct is not None else None for r in target_rows
        ]
        forward_returns = compute_forward_returns(target_returns, horizon=horizon)

        trade_returns = []
        for i, row in enumerate(target_rows):
            rows_by_symbol = {s: series_by_symbol[s].get(row.timestamp) for s in symbols_needed}
            fired = evaluate_rule(rows_by_symbol, conditions)
            if not fired:
                continue
            fill_index = i + fill_lag_periods
            if fill_index < len(forward_returns) and forward_returns[fill_index] is not None:
                trade_returns.append(forward_returns[fill_index])

        trade_returns = apply_trading_costs(trade_returns, fee_pct, slippage_pct)

        metrics = compute_backtest_metrics(trade_returns)
        if metrics is None:
            return None
        metrics["target_symbol"] = target_symbol
        metrics["timeframe"] = timeframe.value
        metrics["horizon_periods"] = horizon
        metrics["fill_lag_periods"] = fill_lag_periods
        metrics["fee_pct"] = fee_pct
        metrics["slippage_pct"] = slippage_pct
        metrics["universe_caveat"] = universe_caveat(target_symbol)
        return metrics
