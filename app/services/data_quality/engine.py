"""Data Quality Engine -- answers a question none of this project's other
engines answer: "does this symbol/timeframe actually have any stored
history at all, and how fresh is it?"

app.services.history.pipeline.run_validation() already checks gaps/
duplicates for symbols that HAVE data, but explicitly skips ones with zero
rows (`if not rows: continue`) -- so a provider that silently returns
nothing for a whole symbol (confirmed live: yfinance returning empty
responses for every YFinanceHistoricalProvider-backed symbol -- all 7
STOCK_TICKERS, all 4 INDEX_TICKERS, DXY/SILVER, on this deployment) was
invisible anywhere except raw process logs. This engine reports exactly
that gap, honestly: only "empty" (zero rows) is treated as a hard status
here -- no fabricated per-symbol staleness threshold, since different
tables have very different natural update cadences (daily OHLCV vs.
monthly FRED macro releases) and guessing wrong would either cry wolf on
legitimately-slow series or hide a real gap on fast ones. Freshness
(days_since_last_update) is still reported as plain, honest context for a
human or a future, cadence-aware check to act on.
"""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.history.registry import HistorySymbolConfig, build_registry
from app.services.history.repository import get_series

# POST-V9 Phase 12: past this many days stale, a symbol's freshness score
# bottoms out at 0 -- a ceiling, not a per-table cadence guess (this
# project's tables have very different natural update cadences, see the
# module docstring; 30 days is a conservative outer bound that only
# penalizes data that's stale by any table's standard).
_STALENESS_CEILING_DAYS = 30


def compute_data_quality_score(days_since_last_update: int | None, status: str) -> int:
    """Pure function: `assess_symbol_quality`'s own output -> a 0-100
    freshness score. 0 for "empty" (no rows at all) or a missing
    `days_since_last_update`; 100 for same-day/next-day freshness; linear
    decay to 0 at `_STALENESS_CEILING_DAYS`. Monotonically non-increasing
    in staleness by construction -- never a guessed, non-monotonic curve."""
    if status == "empty" or days_since_last_update is None:
        return 0
    if days_since_last_update <= 1:
        return 100
    if days_since_last_update >= _STALENESS_CEILING_DAYS:
        return 0
    return round(100 * (1 - days_since_last_update / _STALENESS_CEILING_DAYS))


def assess_symbol_quality(rows: list, now: datetime) -> dict:
    """Pure and directly testable: no rows is the only hard "empty" status;
    any rows at all is "has_data" with row_count/most_recent_timestamp/
    days_since_last_update as plain informational context."""
    if not rows:
        return {
            "status": "empty",
            "row_count": 0,
            "most_recent_timestamp": None,
            "days_since_last_update": None,
        }
    most_recent = rows[-1].timestamp
    return {
        "status": "has_data",
        "row_count": len(rows),
        "most_recent_timestamp": most_recent,
        "days_since_last_update": (now - most_recent).days,
    }


class DataQualityEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def _assess_config(self, config: HistorySymbolConfig, now: datetime) -> list[dict]:
        results = []
        for timeframe in config.timeframes:
            rows = await get_series(self._session_factory, config.model, config.symbol, timeframe)
            assessment = assess_symbol_quality(rows, now)
            results.append(
                {
                    "symbol": config.symbol,
                    "market": config.market,
                    "timeframe": timeframe.value,
                    **assessment,
                }
            )
        return results

    async def assess_all(self) -> dict:
        """Full registry sweep -- every symbol/timeframe combination
        app.services.history.registry.build_registry() knows about."""
        now = datetime.now(UTC)
        results: list[dict] = []
        for config in build_registry():
            results.extend(await self._assess_config(config, now))

        empty = [r for r in results if r["status"] == "empty"]
        return {
            "generated_at": now.isoformat(),
            "results": results,
            "summary": {
                "total": len(results),
                "empty": len(empty),
                "has_data": len(results) - len(empty),
                "empty_symbols": sorted({r["symbol"] for r in empty}),
            },
        }
