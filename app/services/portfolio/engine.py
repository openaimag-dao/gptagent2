"""Portfolio Engine -- virtual portfolio CRUD plus exposure/diversification/
drawdown/health analytics computed against real live prices and real
synced daily history. Reuses `compute_max_drawdown_pct` from the Backtest
Engine (Sprint 9) rather than reimplementing drawdown math a second time.
"""

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import Portfolio, PortfolioPosition
from app.services.backtest.metrics import compute_max_drawdown_pct
from app.services.history.registry import find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.market.repository import MarketRepository
from app.services.portfolio.analytics import (
    CASH_SYMBOL,
    compute_diversification_score,
    compute_exposure,
    compute_health_score,
    compute_risk_score,
    unrealized_pnl_pct,
    value_position,
)

logger = logging.getLogger(__name__)


class PortfolioEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        market_repository: MarketRepository,
    ) -> None:
        self._session_factory = session_factory
        self._market_repository = market_repository

    async def get_or_create(self, name: str = "main") -> Portfolio:
        async with self._session_factory() as session:
            portfolio = await session.scalar(select(Portfolio).where(Portfolio.name == name))
            if portfolio is not None:
                return portfolio
            portfolio = Portfolio(name=name)
            session.add(portfolio)
            await session.commit()
            await session.refresh(portfolio)
            return portfolio

    async def add_position(
        self, portfolio_id: int, symbol: str, quantity: float, entry_price: float | None = None
    ) -> PortfolioPosition:
        symbol = symbol.upper()
        if symbol != CASH_SYMBOL:
            assets = await self._market_repository.get_latest()
            if not any(a.symbol == symbol for a in assets):
                raise ValueError(
                    f"Unknown symbol {symbol}: not currently tracked by the Market Data "
                    "Engine (and not the special CASH symbol)"
                )
        position = PortfolioPosition(
            portfolio_id=portfolio_id, symbol=symbol, quantity=quantity, entry_price=entry_price
        )
        async with self._session_factory() as session:
            session.add(position)
            await session.commit()
            await session.refresh(position)
        return position

    async def remove_position(self, position_id: int) -> bool:
        async with self._session_factory() as session:
            position = await session.get(PortfolioPosition, position_id)
            if position is None:
                return False
            await session.delete(position)
            await session.commit()
            return True

    async def list_positions(self, portfolio_id: int) -> list[PortfolioPosition]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(PortfolioPosition).where(PortfolioPosition.portfolio_id == portfolio_id)
            )
            return list(result)

    async def _weighted_daily_returns(
        self,
        positions: list[PortfolioPosition],
        position_values: dict[int, float],
        total_value: float,
    ) -> list[float] | None:
        """Portfolio daily return series held at CURRENT position weights
        applied to each symbol's own daily return history -- not the
        portfolio's actual historical composition (documented
        simplification). None if any non-cash priced position lacks synced
        daily history, or fewer than 2 aligned trading days exist.
        """
        series_by_symbol: dict[str, dict] = {}
        for position in positions:
            if position.symbol == CASH_SYMBOL or position.id not in position_values:
                continue
            config = find_symbol_config(position.symbol)
            if config is None or Timeframe.DAILY not in config.timeframes:
                return None
            rows = await get_series(
                self._session_factory, config.model, config.symbol, Timeframe.DAILY
            )
            series_by_symbol[position.symbol] = {
                r.timestamp: float(r.return_pct) for r in rows if r.return_pct is not None
            }

        if not series_by_symbol:
            return None

        common_timestamps = set.intersection(*(set(s.keys()) for s in series_by_symbol.values()))
        if len(common_timestamps) < 2:
            return None

        weights = {
            position.symbol: position_values[position.id] / total_value
            for position in positions
            if position.id in position_values and position.symbol in series_by_symbol
        }

        return [
            sum(weights[symbol] * series[ts] for symbol, series in series_by_symbol.items())
            for ts in sorted(common_timestamps)
        ]

    async def compute_health(self, portfolio_id: int) -> dict:
        positions = await self.list_positions(portfolio_id)
        if not positions:
            return {"portfolio_id": portfolio_id, "empty": True, "positions": []}

        assets = await self._market_repository.get_latest()
        by_symbol = {a.symbol: a for a in assets}

        position_values: dict[int, float] = {}
        exposure_values: dict[str, float] = defaultdict(float)
        position_details = []
        priced_count = 0

        for position in positions:
            if position.symbol == CASH_SYMBOL:
                price, asset_class_label = 1.0, "cash"
            else:
                asset = by_symbol.get(position.symbol)
                if asset is None:
                    position_details.append(
                        {
                            "symbol": position.symbol,
                            "quantity": float(position.quantity),
                            "priced": False,
                        }
                    )
                    continue
                price, asset_class_label = float(asset.price), asset.asset_class.value

            value = value_position(float(position.quantity), price)
            position_values[position.id] = value
            exposure_values[asset_class_label] += value
            priced_count += 1
            position_details.append(
                {
                    "symbol": position.symbol,
                    "quantity": float(position.quantity),
                    "priced": True,
                    "price": price,
                    "value": round(value, 2),
                    "asset_class": asset_class_label,
                    "unrealized_pnl_pct": unrealized_pnl_pct(
                        float(position.entry_price) if position.entry_price is not None else None,
                        price,
                    ),
                }
            )

        total_value = sum(position_values.values())
        exposure_pct = compute_exposure(exposure_values)
        diversification_score = compute_diversification_score(exposure_pct)
        data_completeness_pct = round(100 * priced_count / len(positions), 2)

        max_drawdown_pct = None
        if total_value > 0:
            returns = await self._weighted_daily_returns(positions, position_values, total_value)
            if returns is not None:
                max_drawdown_pct = compute_max_drawdown_pct(returns)

        risk_score = compute_risk_score(max_drawdown_pct)
        health_score = compute_health_score(
            data_completeness_pct, diversification_score, risk_score
        )

        return {
            "portfolio_id": portfolio_id,
            "empty": False,
            "total_value": round(total_value, 2),
            "positions": position_details,
            "exposure_pct_by_class": exposure_pct,
            "diversification_score": diversification_score,
            "max_drawdown_pct": max_drawdown_pct,
            "drawdown_note": (
                None
                if max_drawdown_pct is not None
                else "Unavailable: needs synced daily history for every non-cash position "
                "(run sync_history.py), computed at current position weights."
            ),
            "risk_score": risk_score,
            "data_completeness_pct": data_completeness_pct,
            "health_score": health_score,
        }
