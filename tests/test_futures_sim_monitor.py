from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.futures_sim.monitor import _determine_trigger, check_positions_for_triggers
from app.services.futures_sim.orders import OrderRejected


def _position(**overrides):
    defaults = dict(
        id=1,
        account_id=1,
        symbol="BTC",
        side="LONG",
        margin_mode="ISOLATED",
        leverage=20,
        quantity=0.1,
        entry_price=100_000.0,
        mark_price=100_000.0,
        liquidation_price=95_000.0,
        sl_price=None,
        tp_price=None,
        status="OPEN",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---- _determine_trigger (pure function) ------------------------------


def test_long_liquidates_when_price_falls_to_or_below_liquidation_price():
    position = _position(side="LONG", liquidation_price=95_000.0)
    assert _determine_trigger(position, 95_000.0) == "LIQUIDATION"
    assert _determine_trigger(position, 94_000.0) == "LIQUIDATION"
    assert _determine_trigger(position, 96_000.0) is None


def test_short_liquidates_when_price_rises_to_or_above_liquidation_price():
    position = _position(side="SHORT", liquidation_price=105_000.0)
    assert _determine_trigger(position, 105_000.0) == "LIQUIDATION"
    assert _determine_trigger(position, 106_000.0) == "LIQUIDATION"
    assert _determine_trigger(position, 104_000.0) is None


def test_long_stop_loss_triggers_below_sl_price():
    position = _position(side="LONG", liquidation_price=90_000.0, sl_price=98_000.0)
    assert _determine_trigger(position, 97_999.0) == "STOP_LOSS"
    assert _determine_trigger(position, 98_500.0) is None


def test_long_take_profit_triggers_above_tp_price():
    position = _position(side="LONG", liquidation_price=90_000.0, tp_price=110_000.0)
    assert _determine_trigger(position, 110_001.0) == "TAKE_PROFIT"
    assert _determine_trigger(position, 109_999.0) is None


def test_short_stop_loss_and_take_profit_are_mirrored():
    position = _position(
        side="SHORT", liquidation_price=120_000.0, sl_price=102_000.0, tp_price=90_000.0
    )
    assert _determine_trigger(position, 102_001.0) == "STOP_LOSS"
    assert _determine_trigger(position, 89_999.0) == "TAKE_PROFIT"
    assert _determine_trigger(position, 100_000.0) is None


def test_liquidation_takes_priority_over_stop_loss_when_both_have_crossed():
    # a LONG whose price has crashed straight through both its SL and its
    # liquidation price on the same tick -- liquidation is the more severe
    # (and more realistic) outcome, and must win.
    position = _position(side="LONG", liquidation_price=95_000.0, sl_price=98_000.0)
    assert _determine_trigger(position, 94_000.0) == "LIQUIDATION"


def test_no_liquidation_price_never_liquidates():
    position = _position(side="LONG", liquidation_price=None)
    assert _determine_trigger(position, 1.0) is None


# ---- check_positions_for_triggers (integration-ish, mocked I/O) -------


def _monitor_session(positions_scan_return, account_return):
    """Two distinct `async with session_factory() as session:` blocks
    happen per candidate closure in check_positions_for_triggers: the
    initial scan for OPEN positions, and (for anything that triggers) a
    lookup of its account. Both need to come from the same mocked
    session_factory but return different things depending on what's
    queried."""
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=positions_scan_return)
    session.get = AsyncMock(return_value=account_return)
    session.__aenter__.return_value = session
    return MagicMock(return_value=session)


async def test_check_positions_for_triggers_closes_a_liquidated_position():
    position = _position(side="LONG", liquidation_price=95_000.0)
    account = SimpleNamespace(id=1)
    session_factory = _monitor_session([position], account)
    trade = SimpleNamespace(net_pnl=-42.0)

    with (
        patch(
            "app.services.futures_sim.monitor.get_current_price",
            AsyncMock(return_value={"price": 90_000.0}),
        ),
        patch(
            "app.services.futures_sim.monitor.close_position", AsyncMock(return_value=trade)
        ) as mock_close,
    ):
        closures = await check_positions_for_triggers(session_factory, AsyncMock())

    assert len(closures) == 1
    assert closures[0]["exit_reason"] == "LIQUIDATION"
    assert closures[0]["net_pnl"] == -42.0
    assert mock_close.call_args.kwargs["exit_reason"] == "LIQUIDATION"
    assert mock_close.call_args.kwargs["position_id"] == position.id


async def test_check_positions_for_triggers_skips_positions_that_have_not_crossed_anything():
    position = _position(side="LONG", liquidation_price=95_000.0)
    account = SimpleNamespace(id=1)
    session_factory = _monitor_session([position], account)

    with (
        patch(
            "app.services.futures_sim.monitor.get_current_price",
            AsyncMock(return_value={"price": 100_500.0}),
        ),
        patch("app.services.futures_sim.monitor.close_position", AsyncMock()) as mock_close,
    ):
        closures = await check_positions_for_triggers(session_factory, AsyncMock())

    assert closures == []
    mock_close.assert_not_called()


async def test_check_positions_for_triggers_skips_positions_with_no_market_data():
    position = _position(side="LONG", liquidation_price=95_000.0)
    session_factory = _monitor_session([position], SimpleNamespace(id=1))

    with (
        patch("app.services.futures_sim.monitor.get_current_price", AsyncMock(return_value=None)),
        patch("app.services.futures_sim.monitor.close_position", AsyncMock()) as mock_close,
    ):
        closures = await check_positions_for_triggers(session_factory, AsyncMock())

    assert closures == []
    mock_close.assert_not_called()


async def test_check_positions_for_triggers_tolerates_a_concurrent_close():
    position = _position(side="LONG", liquidation_price=95_000.0)
    session_factory = _monitor_session([position], SimpleNamespace(id=1))

    with (
        patch(
            "app.services.futures_sim.monitor.get_current_price",
            AsyncMock(return_value={"price": 90_000.0}),
        ),
        patch(
            "app.services.futures_sim.monitor.close_position",
            AsyncMock(side_effect=OrderRejected("already closed")),
        ),
    ):
        closures = await check_positions_for_triggers(session_factory, AsyncMock())

    assert closures == []  # no exception propagates, no bogus closure recorded


async def test_check_positions_for_triggers_skips_when_account_is_missing():
    position = _position(side="LONG", liquidation_price=95_000.0)
    session_factory = _monitor_session([position], None)

    with (
        patch(
            "app.services.futures_sim.monitor.get_current_price",
            AsyncMock(return_value={"price": 90_000.0}),
        ),
        patch("app.services.futures_sim.monitor.close_position", AsyncMock()) as mock_close,
    ):
        closures = await check_positions_for_triggers(session_factory, AsyncMock())

    assert closures == []
    mock_close.assert_not_called()
