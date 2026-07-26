"""Event Impact Engine (V3 Phase 6): per-event impact measurement --
"what actually happened to BTC/SPX/... around THIS specific FOMC meeting"
rather than the Research Engine's aggregate-across-all-occurrences view.
Reuses get_event_dates (Phase 3) and compute_forward_returns
(probability/engine.py) -- no new statistical machinery, just a different
shape of output (one row per real historical event, not an aggregate).
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.history.registry import find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.probability.engine import compute_forward_returns
from app.services.research.events_lookup import get_event_dates
from app.services.research.matching import nearest_bar_index

logger = logging.getLogger(__name__)

_HORIZONS: dict[str, int] = {
    "return_24h_pct": 1,
    "return_7d_pct": 7,
    "return_30d_pct": 30,
}


class EventImpactEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def measure_impact(
        self,
        event_category: str,
        target_symbol: str,
        timeframe: Timeframe = Timeframe.DAILY,
    ) -> list[dict]:
        """One entry per real historical occurrence of event_category,
        each with the target symbol's own return on the event day
        ("immediate") plus 24h/7d/30d forward returns from that day.
        Empty list if the category/symbol/history isn't available --
        never a fabricated entry."""
        event_dates = await get_event_dates(self._session_factory, event_category)
        if not event_dates:
            return []

        target_config = find_symbol_config(target_symbol)
        if target_config is None or timeframe not in target_config.timeframes:
            return []

        rows = await get_series(
            self._session_factory, target_config.model, target_config.symbol, timeframe
        )
        if not rows:
            return []

        timestamps = [r.timestamp for r in rows]
        returns = [float(r.return_pct) if r.return_pct is not None else None for r in rows]
        forward_by_horizon = {
            key: compute_forward_returns(returns, horizon=horizon)
            for key, horizon in _HORIZONS.items()
        }

        results = []
        for event_date in event_dates:
            idx = nearest_bar_index(timestamps, event_date)
            if idx is None:
                continue
            results.append(
                {
                    "event_date": event_date.isoformat(),
                    "matched_bar_date": timestamps[idx].isoformat(),
                    "immediate_pct": returns[idx],
                    **{key: series[idx] for key, series in forward_by_horizon.items()},
                }
            )

        return results
