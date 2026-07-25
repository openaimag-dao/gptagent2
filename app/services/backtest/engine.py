import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.backtest.conditions import Condition, evaluate_rule
from app.services.backtest.metrics import compute_backtest_metrics
from app.services.history.registry import find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.probability.engine import compute_forward_returns

logger = logging.getLogger(__name__)


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
    ) -> dict | None:
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
            if fired and forward_returns[i] is not None:
                trade_returns.append(forward_returns[i])

        metrics = compute_backtest_metrics(trade_returns)
        if metrics is None:
            return None
        metrics["target_symbol"] = target_symbol
        metrics["timeframe"] = timeframe.value
        metrics["horizon_periods"] = horizon
        return metrics
