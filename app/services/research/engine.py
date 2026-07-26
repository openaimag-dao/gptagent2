"""Research Engine: event-conditioned hypothesis testing ("BTC after CPI",
"BTC after FOMC", "NASDAQ after rate cuts" via the FOMC category, "Gold
after CPI" etc). Reuses the exact same statistical machinery as the
Backtest Engine (compute_forward_returns, compute_backtest_metrics) --
only the "what counts as a trade entry" differs: a curated event date
instead of an indicator condition evaluating True.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.backtest.metrics import compute_backtest_metrics
from app.services.history.registry import find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.probability.engine import compute_forward_returns
from app.services.research.events_lookup import get_event_dates
from app.services.research.matching import nearest_bar_index

logger = logging.getLogger(__name__)


class ResearchEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def test_hypothesis(
        self,
        target_symbol: str,
        event_category: str,
        timeframe: Timeframe = Timeframe.DAILY,
        horizon: int = 1,
    ) -> dict | None:
        """Returns occurrences/avg/median-equivalent/max-gain/max-loss/
        win-rate/confidence-style metrics (compute_backtest_metrics' shape)
        for target_symbol's forward return around every historical
        occurrence of event_category. None if the category is unknown, no
        events are on record, or the symbol has no stored history."""
        event_dates = await get_event_dates(self._session_factory, event_category)
        if not event_dates:
            return None

        target_config = find_symbol_config(target_symbol)
        if target_config is None or timeframe not in target_config.timeframes:
            return None

        rows = await get_series(
            self._session_factory, target_config.model, target_config.symbol, timeframe
        )
        if not rows:
            return None

        timestamps = [r.timestamp for r in rows]
        returns = [float(r.return_pct) if r.return_pct is not None else None for r in rows]
        forward_returns = compute_forward_returns(returns, horizon=horizon)

        trade_returns = []
        matched_dates = []
        for event_date in event_dates:
            idx = nearest_bar_index(timestamps, event_date)
            if idx is None or forward_returns[idx] is None:
                continue
            trade_returns.append(forward_returns[idx])
            matched_dates.append(timestamps[idx].isoformat())

        metrics = compute_backtest_metrics(trade_returns)
        if metrics is None:
            return None
        metrics["target_symbol"] = target_config.symbol
        metrics["event_category"] = event_category.lower()
        metrics["timeframe"] = timeframe.value
        metrics["horizon_periods"] = horizon
        metrics["matched_dates"] = matched_dates
        return metrics
