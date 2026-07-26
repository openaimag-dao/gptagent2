"""Strategy Lab: extends the Backtest Engine (same Condition DSL, same
compute_backtest_metrics) with early exits (stop-loss/take-profit),
position sizing, walk-forward testing and Monte Carlo resampling. Reuses
BacktestEngine's row-loading/condition-firing pattern rather than
duplicating it -- the difference is that a "trade" here compounds the real
day-by-day path to `horizon` (so stop-loss/take-profit can trigger early)
instead of BacktestEngine's single terminal-bar return.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.backtest.conditions import Condition, evaluate_rule
from app.services.backtest.engine import _row_to_dict
from app.services.backtest.metrics import compute_backtest_metrics
from app.services.backtest.strategy import (
    apply_position_size,
    monte_carlo_simulation,
    simulate_trade_exit,
)
from app.services.history.registry import HistorySymbolConfig, find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe

logger = logging.getLogger(__name__)

_MIN_ROWS_PER_FOLD = 10


class StrategyLabEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def _load(
        self, conditions: list[Condition], target_symbol: str, timeframe: Timeframe
    ) -> tuple[HistorySymbolConfig, list, dict] | None:
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

        target_rows = list(
            await get_series(
                self._session_factory, target_config.model, target_config.symbol, timeframe
            )
        )
        if not target_rows:
            return None
        return target_config, target_rows, series_by_symbol

    def _trade_returns_for_range(
        self,
        conditions: list[Condition],
        target_rows: list,
        raw_returns: list[float | None],
        series_by_symbol: dict,
        symbols_needed: set[str],
        horizon: int,
        stop_loss_pct: float | None,
        take_profit_pct: float | None,
        position_size_pct: float,
        start: int,
        end: int,
    ) -> list[float]:
        trade_returns = []
        for i in range(start, end):
            row = target_rows[i]
            rows_by_symbol = {s: series_by_symbol[s].get(row.timestamp) for s in symbols_needed}
            if not evaluate_rule(rows_by_symbol, conditions):
                continue
            future = [r for r in raw_returns[i + 1 : i + 1 + horizon] if r is not None]
            if len(future) < horizon:
                continue
            realized = simulate_trade_exit(future, stop_loss_pct, take_profit_pct)
            if realized is None:
                continue
            trade_returns.append(apply_position_size(realized, position_size_pct))
        return trade_returns

    async def run(
        self,
        conditions: list[Condition],
        target_symbol: str,
        timeframe: Timeframe = Timeframe.DAILY,
        horizon: int = 1,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        position_size_pct: float = 1.0,
    ) -> dict | None:
        loaded = await self._load(conditions, target_symbol, timeframe)
        if loaded is None:
            return None
        target_config, target_rows, series_by_symbol = loaded
        raw_returns = [
            float(r.return_pct) if r.return_pct is not None else None for r in target_rows
        ]
        symbols_needed = {c.symbol for c in conditions} | {target_symbol}

        trade_returns = self._trade_returns_for_range(
            conditions,
            target_rows,
            raw_returns,
            series_by_symbol,
            symbols_needed,
            horizon,
            stop_loss_pct,
            take_profit_pct,
            position_size_pct,
            0,
            len(target_rows),
        )
        metrics = compute_backtest_metrics(trade_returns)
        if metrics is None:
            return None
        metrics.update(
            {
                "target_symbol": target_config.symbol,
                "timeframe": timeframe.value,
                "horizon_periods": horizon,
                "stop_loss_pct": stop_loss_pct,
                "take_profit_pct": take_profit_pct,
                "position_size_pct": position_size_pct,
            }
        )
        return metrics

    async def walk_forward(
        self,
        conditions: list[Condition],
        target_symbol: str,
        timeframe: Timeframe = Timeframe.DAILY,
        horizon: int = 1,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        position_size_pct: float = 1.0,
        folds: int = 4,
    ) -> list[dict]:
        """Splits the full stored history into `folds` contiguous
        chronological windows and reruns the SAME rule in each -- this
        project has no optimizer, so walk-forward here means "does this
        already-defined rule hold up consistently across time", not
        re-fitting parameters per fold."""
        loaded = await self._load(conditions, target_symbol, timeframe)
        if loaded is None:
            return []
        target_config, target_rows, series_by_symbol = loaded
        if len(target_rows) < folds * _MIN_ROWS_PER_FOLD:
            return []

        raw_returns = [
            float(r.return_pct) if r.return_pct is not None else None for r in target_rows
        ]
        symbols_needed = {c.symbol for c in conditions} | {target_symbol}
        fold_size = len(target_rows) // folds

        results = []
        for fold_idx in range(folds):
            start = fold_idx * fold_size
            end = len(target_rows) if fold_idx == folds - 1 else start + fold_size
            trade_returns = self._trade_returns_for_range(
                conditions,
                target_rows,
                raw_returns,
                series_by_symbol,
                symbols_needed,
                horizon,
                stop_loss_pct,
                take_profit_pct,
                position_size_pct,
                start,
                end,
            )
            results.append(
                {
                    "fold": fold_idx + 1,
                    "start_date": target_rows[start].timestamp.isoformat(),
                    "end_date": target_rows[end - 1].timestamp.isoformat(),
                    "metrics": compute_backtest_metrics(trade_returns),
                }
            )
        return results

    async def monte_carlo(
        self,
        conditions: list[Condition],
        target_symbol: str,
        timeframe: Timeframe = Timeframe.DAILY,
        horizon: int = 1,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        position_size_pct: float = 1.0,
        n_simulations: int = 1000,
        seed: int | None = None,
    ) -> dict | None:
        loaded = await self._load(conditions, target_symbol, timeframe)
        if loaded is None:
            return None
        target_config, target_rows, series_by_symbol = loaded
        raw_returns = [
            float(r.return_pct) if r.return_pct is not None else None for r in target_rows
        ]
        symbols_needed = {c.symbol for c in conditions} | {target_symbol}

        trade_returns = self._trade_returns_for_range(
            conditions,
            target_rows,
            raw_returns,
            series_by_symbol,
            symbols_needed,
            horizon,
            stop_loss_pct,
            take_profit_pct,
            position_size_pct,
            0,
            len(target_rows),
        )
        result = monte_carlo_simulation(trade_returns, n_simulations=n_simulations, seed=seed)
        if result is None:
            return None
        result["target_symbol"] = target_config.symbol
        return result
