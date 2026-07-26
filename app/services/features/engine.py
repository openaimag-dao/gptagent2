"""Feature Engine: computes and persists derived features not already
covered by the per-row indicators stored in the history tables (RSI/MACD/
ATR/SMA/return/volatility) or by another engine's own snapshot. Reuses
CorrelationEngine (correlation), backtest/metrics.py (Sharpe/Sortino/
drawdown), GlobalScoreEngine (liquidity) and SentimentEngine (fear/greed)
rather than recomputing any of those here -- this engine only adds what
those don't already produce: beta, cointegration, market breadth, rolling
multi-window momentum, and funding-rate/open-interest momentum derived from
the persisted WhaleSnapshot history.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import FeatureSnapshot, WhaleSnapshot
from app.database.redis import get_redis
from app.services.features.math import (
    compute_beta,
    compute_cointegration,
    compute_market_breadth,
    compute_momentum_delta,
    compute_returns,
    compute_rolling_momentum,
)
from app.services.history.registry import find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.market.repository import MarketRepository
from app.services.market.stocks.provider import MAGNIFICENT_SEVEN

logger = logging.getLogger(__name__)

_MOMENTUM_WINDOWS: tuple[int, ...] = (7, 14, 30, 90)
_HISTORY_LIMIT = 300
_WHALE_HISTORY_LIMIT = 10


class FeatureEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        market_repository: MarketRepository | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._market_repository = market_repository or MarketRepository(
            session_factory, get_redis()
        )

    async def _closes(self, symbol: str, timeframe: Timeframe = Timeframe.DAILY) -> list[float]:
        config = find_symbol_config(symbol)
        if config is None or timeframe not in config.timeframes:
            return []
        rows = await get_series(self._session_factory, config.model, config.symbol, timeframe)
        return [float(r.close) for r in rows[-_HISTORY_LIMIT:]]

    async def _whale_history(self, symbol: str) -> list[WhaleSnapshot]:
        async with self._session_factory() as session:
            rows = list(
                await session.scalars(
                    select(WhaleSnapshot)
                    .where(WhaleSnapshot.symbol == symbol.upper(), WhaleSnapshot.available)
                    .order_by(WhaleSnapshot.computed_at.desc())
                    .limit(_WHALE_HISTORY_LIMIT)
                )
            )
        return list(reversed(rows))

    async def compute_and_store(
        self, symbol: str, benchmark_symbol: str = "NASDAQ"
    ) -> FeatureSnapshot:
        features: dict = {}

        closes = await self._closes(symbol)
        for window in _MOMENTUM_WINDOWS:
            momentum = compute_rolling_momentum(closes, window)
            if momentum is not None:
                features[f"momentum_{window}d_pct"] = momentum

        if symbol.upper() != benchmark_symbol.upper():
            benchmark_closes = await self._closes(benchmark_symbol)
            if closes and benchmark_closes:
                beta = compute_beta(compute_returns(closes), compute_returns(benchmark_closes))
                if beta is not None:
                    features[f"beta_vs_{benchmark_symbol.lower()}"] = beta

                coint = compute_cointegration(closes, benchmark_closes)
                if coint is not None:
                    features[f"cointegration_vs_{benchmark_symbol.lower()}"] = {
                        "hedge_ratio": coint["hedge_ratio"],
                        "statistic": coint["statistic"],
                        "is_stationary": coint["is_stationary"],
                    }

        assets = await self._market_repository.get_latest()
        breadth_inputs = [
            float(a.change_pct_24h)
            for a in assets
            if a.symbol in MAGNIFICENT_SEVEN and a.change_pct_24h is not None
        ]
        breadth = compute_market_breadth(breadth_inputs)
        if breadth is not None:
            features["market_breadth_mag7_pct"] = breadth

        whale_rows = await self._whale_history(symbol)
        funding_rates = [
            row.data["funding_rate"] for row in whale_rows if row.data.get("funding_rate")
        ]
        open_interests = [
            row.data["open_interest"] for row in whale_rows if row.data.get("open_interest")
        ]
        funding_momentum = compute_momentum_delta(funding_rates)
        if funding_momentum is not None:
            features["funding_rate_momentum_pct"] = funding_momentum
        oi_change = compute_momentum_delta(open_interests)
        if oi_change is not None:
            features["open_interest_change_pct"] = oi_change

        row = FeatureSnapshot(symbol=symbol.upper(), features=features)
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def get_latest(self, symbol: str) -> FeatureSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(FeatureSnapshot)
                .where(FeatureSnapshot.symbol == symbol.upper())
                .order_by(FeatureSnapshot.computed_at.desc())
                .limit(1)
            )
