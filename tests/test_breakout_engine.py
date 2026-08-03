from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.breakout.engine import BreakoutEngine
from app.services.history.schemas import Timeframe


def _session_factory(scalars_return):
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=scalars_return)
    session.__aenter__.return_value = session
    return MagicMock(return_value=session)


def _event(symbol, computed_at):
    return SimpleNamespace(symbol=symbol, computed_at=computed_at)


async def test_get_latest_across_returns_empty_when_no_rows():
    engine = BreakoutEngine(_session_factory([]), AsyncMock(), AsyncMock())

    result = await engine.get_latest_across(["BTC", "ETH"], Timeframe.DAILY)

    assert result == []


async def test_get_latest_across_keeps_only_most_recent_per_symbol():
    newer_btc = _event("BTC", datetime(2026, 8, 3, tzinfo=UTC))
    older_btc = _event("BTC", datetime(2026, 8, 1, tzinfo=UTC))
    eth = _event("ETH", datetime(2026, 8, 2, tzinfo=UTC))
    # session.scalars() is mocked to already return in computed_at-desc order,
    # matching the real query's ORDER BY.
    engine = BreakoutEngine(_session_factory([newer_btc, eth, older_btc]), AsyncMock(), AsyncMock())

    result = await engine.get_latest_across(["BTC", "ETH"], Timeframe.DAILY)

    assert result == [newer_btc, eth]
