from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.futures_sim.orders import OrderRejected
from app.services.futures_sim.resting_orders import (
    _fill_reference,
    _should_fill,
    check_resting_orders_for_fills,
)


def _order(**overrides):
    defaults = dict(
        id=1,
        account_id=1,
        symbol="BTC",
        side="BUY",
        order_type="LIMIT",
        quantity=0.1,
        leverage=20,
        margin_mode="ISOLATED",
        reduce_only=False,
        price=None,
        stop_price=None,
        status="NEW",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---- _should_fill (pure function) --------------------------------------


def test_buy_limit_fills_at_or_below_its_price():
    order = _order(order_type="LIMIT", side="BUY", price=90_000.0)
    assert _should_fill(order, 90_000.0) is True
    assert _should_fill(order, 89_999.0) is True
    assert _should_fill(order, 90_001.0) is False


def test_sell_limit_fills_at_or_above_its_price():
    order = _order(order_type="LIMIT", side="SELL", price=110_000.0)
    assert _should_fill(order, 110_000.0) is True
    assert _should_fill(order, 110_001.0) is True
    assert _should_fill(order, 109_999.0) is False


def test_buy_stop_market_triggers_at_or_above_stop_price():
    order = _order(order_type="STOP_MARKET", side="BUY", stop_price=105_000.0)
    assert _should_fill(order, 105_000.0) is True
    assert _should_fill(order, 105_001.0) is True
    assert _should_fill(order, 104_999.0) is False


def test_sell_stop_market_triggers_at_or_below_stop_price():
    order = _order(order_type="STOP_MARKET", side="SELL", stop_price=95_000.0)
    assert _should_fill(order, 95_000.0) is True
    assert _should_fill(order, 94_999.0) is True
    assert _should_fill(order, 95_001.0) is False


def test_take_profit_market_uses_the_same_trigger_direction_as_stop_market():
    buy_tp = _order(order_type="TAKE_PROFIT_MARKET", side="BUY", stop_price=105_000.0)
    sell_tp = _order(order_type="TAKE_PROFIT_MARKET", side="SELL", stop_price=95_000.0)
    assert _should_fill(buy_tp, 106_000.0) is True
    assert _should_fill(sell_tp, 94_000.0) is True


# ---- _fill_reference (pure function) -----------------------------------


def test_limit_fill_reference_uses_the_orders_own_price_with_no_slippage():
    order = _order(order_type="LIMIT", side="BUY", price=90_000.0)
    fill = _fill_reference(order, current_price=89_500.0)
    assert fill["actual_fill_price"] == 90_000.0
    assert fill["slippage_pct"] == 0.0


def test_stop_market_fill_reference_applies_slippage_against_current_price():
    order = _order(order_type="STOP_MARKET", side="BUY", stop_price=105_000.0)
    fill = _fill_reference(order, current_price=105_100.0)
    assert fill["actual_fill_price"] > fill["requested_price"]  # BUY pays up
    assert fill["requested_price"] == 105_100.0


# ---- check_resting_orders_for_fills (mocked I/O) ------------------------


def _resting_session(order_get, account_get):
    session = AsyncMock()
    session.get = AsyncMock(side_effect=[order_get, account_get])
    session.__aenter__.return_value = session
    return session


def _session_factory_sequence(scan_session, per_order_sessions):
    """The scan happens in its own `async with` block, and then one more
    per candidate order that crosses its trigger -- session_factory() is
    called once per block, so give it a side_effect list."""
    calls = iter([scan_session, *per_order_sessions])
    return MagicMock(side_effect=lambda: next(calls))


async def test_check_resting_orders_for_fills_fills_a_crossed_limit_order():
    order = _order(order_type="LIMIT", side="BUY", price=90_000.0)
    scan_session = AsyncMock()
    scan_session.scalars = AsyncMock(return_value=[order])
    scan_session.__aenter__.return_value = scan_session

    fill_session = _resting_session(order_get=order, account_get=SimpleNamespace(id=1))

    session_factory = _session_factory_sequence(scan_session, [fill_session])

    with (
        patch(
            "app.services.futures_sim.resting_orders.get_current_price",
            AsyncMock(return_value={"price": 89_000.0}),
        ),
        patch(
            "app.services.futures_sim.resting_orders._open_position_for_symbol",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.futures_sim.resting_orders.execute_fill", AsyncMock(return_value={})
        ) as mock_execute,
    ):
        filled = await check_resting_orders_for_fills(session_factory, AsyncMock())

    assert len(filled) == 1
    assert filled[0]["order_id"] == order.id
    mock_execute.assert_awaited_once()
    # LIMIT fills at exactly its own price, not the current price
    assert mock_execute.call_args.kwargs["fill"]["actual_fill_price"] == 90_000.0


async def test_check_resting_orders_for_fills_skips_orders_not_yet_crossed():
    order = _order(order_type="LIMIT", side="BUY", price=90_000.0)
    scan_session = AsyncMock()
    scan_session.scalars = AsyncMock(return_value=[order])
    scan_session.__aenter__.return_value = scan_session
    session_factory = MagicMock(return_value=scan_session)

    with (
        patch(
            "app.services.futures_sim.resting_orders.get_current_price",
            AsyncMock(return_value={"price": 91_000.0}),
        ),
        patch("app.services.futures_sim.resting_orders.execute_fill", AsyncMock()) as mock_execute,
    ):
        filled = await check_resting_orders_for_fills(session_factory, AsyncMock())

    assert filled == []
    mock_execute.assert_not_called()


async def test_check_resting_orders_for_fills_skips_orders_with_no_market_data():
    order = _order(order_type="LIMIT", side="BUY", price=90_000.0)
    scan_session = AsyncMock()
    scan_session.scalars = AsyncMock(return_value=[order])
    scan_session.__aenter__.return_value = scan_session
    session_factory = MagicMock(return_value=scan_session)

    with patch(
        "app.services.futures_sim.resting_orders.get_current_price", AsyncMock(return_value=None)
    ):
        filled = await check_resting_orders_for_fills(session_factory, AsyncMock())

    assert filled == []


async def test_check_resting_orders_for_fills_tolerates_a_concurrent_cancel():
    order = _order(order_type="LIMIT", side="BUY", price=90_000.0)
    scan_session = AsyncMock()
    scan_session.scalars = AsyncMock(return_value=[order])
    scan_session.__aenter__.return_value = scan_session

    # re-fetched order shows CANCELLED -- a concurrent cancel beat this scan
    cancelled_order = _order(order_type="LIMIT", side="BUY", price=90_000.0, status="CANCELLED")
    fill_session = _resting_session(order_get=cancelled_order, account_get=SimpleNamespace(id=1))
    session_factory = _session_factory_sequence(scan_session, [fill_session])

    with (
        patch(
            "app.services.futures_sim.resting_orders.get_current_price",
            AsyncMock(return_value={"price": 89_000.0}),
        ),
        patch("app.services.futures_sim.resting_orders.execute_fill", AsyncMock()) as mock_execute,
    ):
        filled = await check_resting_orders_for_fills(session_factory, AsyncMock())

    assert filled == []
    mock_execute.assert_not_called()


async def test_check_resting_orders_for_fills_tolerates_order_rejected_at_fill_time():
    order = _order(order_type="LIMIT", side="BUY", price=90_000.0)
    scan_session = AsyncMock()
    scan_session.scalars = AsyncMock(return_value=[order])
    scan_session.__aenter__.return_value = scan_session

    fill_session = _resting_session(order_get=order, account_get=SimpleNamespace(id=1))
    session_factory = _session_factory_sequence(scan_session, [fill_session])

    with (
        patch(
            "app.services.futures_sim.resting_orders.get_current_price",
            AsyncMock(return_value={"price": 89_000.0}),
        ),
        patch(
            "app.services.futures_sim.resting_orders._open_position_for_symbol",
            AsyncMock(return_value=None),
        ),
        patch(
            "app.services.futures_sim.resting_orders.execute_fill",
            AsyncMock(side_effect=OrderRejected("Insufficient margin")),
        ),
    ):
        filled = await check_resting_orders_for_fills(session_factory, AsyncMock())

    assert filled == []  # no exception propagates, no bogus fill recorded
