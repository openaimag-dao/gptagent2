from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.database.models import FuturesSimAccount, FuturesSimOrder, FuturesSimPosition
from app.services.futures_sim.orders import (
    OrderRejected,
    cancel_order,
    close_position,
    place_limit_order,
    place_market_order,
    place_stop_order,
    set_stop_loss_take_profit,
)


def _orders_session(
    scalar_side_effect=None, scalars_return=None, account=None, position_get=None, order_get=None
):
    """`session.get` is called for several different purposes across
    orders.py (re-binding the account to this session, fetching a
    position, fetching an order to cancel), so it needs to dispatch by
    model class rather than return one fixed value."""

    async def _get(model, _ident):
        if model is FuturesSimAccount:
            return account
        if model is FuturesSimPosition:
            return position_get
        if model is FuturesSimOrder:
            return order_get
        return None

    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=scalar_side_effect or [None])
    session.scalars = AsyncMock(return_value=scalars_return if scalars_return is not None else [])
    session.add = MagicMock()  # Session.add is sync in real SQLAlchemy, never awaited
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.get = AsyncMock(side_effect=_get)
    session.__aenter__.return_value = session
    return MagicMock(return_value=session), session


def _account(**overrides):
    defaults = dict(id=1, wallet_balance=10_000.0, fees_paid_total=0.0, realized_pnl_total=0.0)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _open_position(**overrides):
    defaults = dict(
        id=7,
        account_id=1,
        symbol="BTC",
        side="LONG",
        margin_mode="ISOLATED",
        leverage=20,
        quantity=0.1,
        entry_price=100_000.0,
        mark_price=100_000.0,
        initial_margin=500.0,
        maintenance_margin=40.0,
        realized_pnl=0.0,
        funding_paid=0.0,
        liquidation_price=None,
        status="OPEN",
        opened_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        closed_at=None,
        close_reason=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _price(value):
    return AsyncMock(return_value={"price": value})


# ---- place_market_order: opening ------------------------------------------


async def test_open_new_long_position_via_market_order():
    account = _account()
    session_factory, session = _orders_session(scalar_side_effect=[None, None], account=account)

    with patch("app.services.futures_sim.orders.get_current_price", _price(100_000.0)):
        result = await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="BUY",
            quantity=0.1,
            leverage=20,
        )

    assert result["idempotent_replay"] is False
    order = result["order"]
    assert order.status == "FILLED"
    assert order.filled_quantity == 0.1
    position = result["position"]
    assert position.side == "LONG"
    assert position.quantity == 0.1
    assert position.entry_price == pytest.approx(100_020.0)  # +0.02% slippage
    assert position.initial_margin == pytest.approx(500.1, rel=1e-3)
    # fee (taker 0.04% of notional) deducted from wallet balance
    assert account.wallet_balance < 10_000.0


async def test_open_new_short_position_via_market_order():
    account = _account()
    session_factory, session = _orders_session(scalar_side_effect=[None, None], account=account)

    with patch("app.services.futures_sim.orders.get_current_price", _price(100_000.0)):
        result = await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="SELL",
            quantity=0.1,
            leverage=10,
        )

    position = result["position"]
    assert position.side == "SHORT"
    assert position.entry_price == pytest.approx(99_980.0)  # -0.02% slippage


async def test_open_new_position_cross_mode_computes_liquidation_price_from_account_equity():
    account = _account(wallet_balance=10_000.0)
    session_factory, session = _orders_session(
        scalar_side_effect=[None, None], account=account, scalars_return=[]
    )

    with patch("app.services.futures_sim.orders.get_current_price", _price(100_000.0)):
        result = await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="BUY",
            quantity=0.1,
            leverage=20,
            margin_mode="CROSS",
        )

    position = result["position"]
    assert position.margin_mode == "CROSS"
    # $10k of account equity backing a $500-margin position is an enormous
    # cushion -- liquidation price is far below (much more negative than)
    # the ISOLATED equivalent for the same inputs (95_400.0).
    assert position.liquidation_price < 0


async def test_cross_liquidation_price_accounts_for_other_open_positions_unrealized_pnl():
    async def _price_by_symbol(_session_factory, _redis, symbol):
        return {"price": 100_000.0 if symbol == "BTC" else 2_500.0}

    # baseline: no other open positions
    account_alone = _account(wallet_balance=10_000.0)
    session_factory_alone, _ = _orders_session(
        scalar_side_effect=[None, None], account=account_alone, scalars_return=[]
    )
    with patch(
        "app.services.futures_sim.orders.get_current_price", AsyncMock(side_effect=_price_by_symbol)
    ):
        result_alone = await place_market_order(
            account_alone,
            session_factory_alone,
            AsyncMock(),
            symbol="BTC",
            side="BUY",
            quantity=0.1,
            leverage=20,
            margin_mode="CROSS",
        )

    # same account, but with an ETH LONG that's up $500 in unrealized PnL
    account_with_gain = _account(wallet_balance=10_000.0)
    other_position = _open_position(
        id=2, symbol="ETH", side="LONG", quantity=1.0, entry_price=2_000.0, mark_price=2_000.0
    )
    session_factory_with_gain, _ = _orders_session(
        scalar_side_effect=[None, None], account=account_with_gain, scalars_return=[other_position]
    )
    with patch(
        "app.services.futures_sim.orders.get_current_price", AsyncMock(side_effect=_price_by_symbol)
    ):
        result_with_gain = await place_market_order(
            account_with_gain,
            session_factory_with_gain,
            AsyncMock(),
            symbol="BTC",
            side="BUY",
            quantity=0.1,
            leverage=20,
            margin_mode="CROSS",
        )

    # more account equity (from the other position's unrealized gain) ->
    # more cushion -> a LONG's liquidation price moves further away (lower)
    assert (
        result_with_gain["position"].liquidation_price < result_alone["position"].liquidation_price
    )


async def test_open_new_position_rejects_insufficient_margin():
    account = _account(wallet_balance=10.0)  # far too little for a $10k notional position
    session_factory, session = _orders_session(scalar_side_effect=[None, None], account=account)

    with (
        patch("app.services.futures_sim.orders.get_current_price", _price(100_000.0)),
        pytest.raises(OrderRejected, match="Insufficient margin"),
    ):
        await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="BUY",
            quantity=0.1,
            leverage=20,
        )


async def test_place_market_order_rejects_when_no_market_data():
    account = _account()
    session_factory, session = _orders_session(scalar_side_effect=[None, None], account=account)

    with (
        patch("app.services.futures_sim.orders.get_current_price", AsyncMock(return_value=None)),
        pytest.raises(OrderRejected, match="No market data available"),
    ):
        await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="BUY",
            quantity=0.1,
            leverage=20,
        )
    session.commit.assert_awaited()  # the REJECTED order row was still persisted


async def test_place_market_order_rejects_invalid_side():
    account = _account()
    session_factory, _ = _orders_session(scalar_side_effect=[None, None], account=account)
    with pytest.raises(OrderRejected, match="side must be BUY or SELL"):
        await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="HOLD",
            quantity=0.1,
            leverage=20,
        )


async def test_place_market_order_rejects_leverage_above_symbol_bracket():
    account = _account()
    session_factory, _ = _orders_session(scalar_side_effect=[None, None], account=account)
    with pytest.raises(ValueError, match="max leverage"):
        await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="SUI",
            side="BUY",
            quantity=1,
            leverage=75,
        )


# ---- idempotency ------------------------------------------------------


async def test_duplicate_client_order_id_returns_existing_order_without_reexecuting():
    existing_order = SimpleNamespace(id=99, position_id=None, client_order_id="abc")
    session_factory, session = _orders_session(scalar_side_effect=[existing_order])

    with patch("app.services.futures_sim.orders.get_current_price") as mock_price:
        result = await place_market_order(
            _account(),
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="BUY",
            quantity=0.1,
            leverage=20,
            client_order_id="abc",
        )

    assert result["idempotent_replay"] is True
    assert result["order"] is existing_order
    mock_price.assert_not_called()  # never re-priced/re-executed


# ---- reduceOnly semantics ----------------------------------------------


async def test_reduce_only_rejected_when_no_open_position():
    session_factory, _ = _orders_session(scalar_side_effect=[None, None], account=_account())
    with (
        patch("app.services.futures_sim.orders.get_current_price", _price(100_000.0)),
        pytest.raises(OrderRejected, match="no open position to reduce"),
    ):
        await place_market_order(
            _account(),
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="SELL",
            quantity=0.1,
            leverage=10,
            reduce_only=True,
        )


async def test_reduce_only_rejected_when_it_would_increase_exposure():
    position = _open_position(side="LONG")
    session_factory, _ = _orders_session(scalar_side_effect=[None, position], account=_account())
    with (
        patch("app.services.futures_sim.orders.get_current_price", _price(100_000.0)),
        pytest.raises(OrderRejected, match="would increase exposure"),
    ):
        await place_market_order(
            _account(),
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="BUY",  # same direction as the existing LONG
            quantity=0.1,
            leverage=10,
            reduce_only=True,
        )


async def test_reduce_only_caps_close_quantity_instead_of_flipping():
    position = _open_position(side="LONG", quantity=0.1)
    account = _account()
    # scalar calls: existing_order check, initial position lookup, re-fetch after close
    session_factory, session = _orders_session(
        scalar_side_effect=[None, position, None], account=account
    )

    with patch("app.services.futures_sim.orders.get_current_price", _price(102_000.0)):
        result = await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="SELL",
            quantity=0.15,  # exceeds the 0.1 position size
            leverage=20,
            reduce_only=True,
        )

    assert result["position"] is None  # capped at close, never flipped into a new SHORT
    assert result["order"].filled_quantity == pytest.approx(0.1)  # only what actually executed
    assert result["trade"] is not None
    assert position.status == "CLOSED"


# ---- increase / close / flip -------------------------------------------


async def test_increase_existing_position_recomputes_weighted_average_entry():
    position = _open_position(
        side="LONG", quantity=0.1, entry_price=100_000.0, initial_margin=500.0
    )
    account = _account()
    session_factory, session = _orders_session(
        scalar_side_effect=[None, position], scalars_return=[position], account=account
    )

    with patch("app.services.futures_sim.orders.get_current_price", _price(102_000.0)):
        result = await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="BUY",
            quantity=0.1,
            leverage=20,
        )

    assert result["position"] is position
    assert position.quantity == pytest.approx(0.2)
    # weighted average of 100_000 (existing) and ~102_020.4 (new fill)
    assert position.entry_price == pytest.approx(101_010.2, rel=1e-4)


async def test_close_full_position_realizes_pnl_and_marks_position_closed():
    position = _open_position(side="LONG", quantity=0.1, entry_price=100_000.0)
    account = _account()
    session_factory, session = _orders_session(
        scalar_side_effect=[None, position, None], account=account
    )

    with patch("app.services.futures_sim.orders.get_current_price", _price(102_000.0)):
        result = await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="SELL",
            quantity=0.1,
            leverage=20,
        )

    trade = result["trade"]
    assert trade is not None
    assert trade.gross_pnl == pytest.approx(197.96, rel=1e-3)  # (101979.6-100000)*0.1
    assert trade.net_pnl < trade.gross_pnl  # fee subtracted
    assert result["position"] is None
    assert position.status == "CLOSED"
    assert position.close_reason == "MANUAL"
    assert account.realized_pnl_total == pytest.approx(trade.net_pnl)


async def test_close_partial_position_leaves_the_remainder_open():
    position = _open_position(side="LONG", quantity=0.1, entry_price=100_000.0)
    account = _account()
    session_factory, session = _orders_session(
        scalar_side_effect=[None, position, position], account=account
    )

    with patch("app.services.futures_sim.orders.get_current_price", _price(102_000.0)):
        result = await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="SELL",
            quantity=0.05,
            leverage=20,
        )

    assert result["trade"] is not None
    assert position.status == "OPEN"
    assert position.quantity == pytest.approx(0.05)
    assert result["position"] is position


async def test_flip_position_closes_then_opens_the_opposite_side_with_the_remainder():
    position = _open_position(side="LONG", quantity=0.1, entry_price=100_000.0)
    account = _account()
    session_factory, session = _orders_session(scalar_side_effect=[None, position], account=account)

    with patch("app.services.futures_sim.orders.get_current_price", _price(102_000.0)):
        result = await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="SELL",
            quantity=0.15,  # 0.1 closes the LONG, 0.05 flips into a new SHORT
            leverage=20,
        )

    assert result["trade"] is not None
    new_position = result["position"]
    assert new_position is not position
    assert new_position.side == "SHORT"
    assert new_position.quantity == pytest.approx(0.05)
    assert result["order"].filled_quantity == pytest.approx(0.15)
    assert position.status == "CLOSED"


async def test_flip_does_not_double_charge_fees_on_the_overlap_quantity():
    """Regression test: the close leg's fee must be computed on the actually
    closed quantity, not the full requested quantity -- otherwise the
    remainder's notional gets charged a fee twice (once via the close leg,
    once via the new position's own open fee)."""
    position = _open_position(side="LONG", quantity=0.1, entry_price=100_000.0)
    account = _account()
    session_factory, session = _orders_session(scalar_side_effect=[None, position], account=account)

    with patch("app.services.futures_sim.orders.get_current_price", _price(102_000.0)):
        result = await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="SELL",
            quantity=0.15,
            leverage=20,
        )

    trade = result["trade"]
    order = result["order"]
    # fee is linear in notional, so total order fee should equal fee(0.15
    # units) exactly -- not fee(0.1) [close] + fee(0.05) [flip open], which
    # would double-count the 0.05 overlap and not equal this value.
    total_notional = 0.15 * float(order.actual_fill_price)
    expected_total_fee = total_notional * 0.04 / 100
    assert order.fee_amount == pytest.approx(expected_total_fee, rel=1e-6)
    # the close leg's own fee must be on 0.1 units only, not 0.15
    close_notional = 0.1 * float(order.actual_fill_price)
    assert trade.fees == pytest.approx(close_notional * 0.04 / 100, rel=1e-6)


async def test_fee_and_realized_pnl_persist_on_the_orders_own_session_bound_account():
    """Regression test: `account` is loaded by a *different* (already
    closed) session before place_market_order is ever called -- mutating
    its wallet_balance in place and committing THIS function's own session
    must not silently drop those writes. place_market_order must re-bind to
    its own session's copy of the row before mutating it."""
    position = _open_position(side="LONG", quantity=0.1, entry_price=100_000.0)
    detached_account = _account()  # simulates an account loaded by a prior, closed session
    session_bound_account = _account()  # the "real" row, as this session's `session.get` sees it
    session_factory, session = _orders_session(
        scalar_side_effect=[None, position, None], account=session_bound_account
    )

    with patch("app.services.futures_sim.orders.get_current_price", _price(102_000.0)):
        result = await place_market_order(
            detached_account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="SELL",
            quantity=0.1,
            leverage=20,
        )

    # the detached object passed in by the caller must be untouched...
    assert detached_account.wallet_balance == 10_000.0
    assert detached_account.realized_pnl_total == 0.0
    # ...and every mutation must have landed on the session-bound instance,
    # the one that actually gets committed.
    assert session_bound_account.wallet_balance != 10_000.0
    assert session_bound_account.realized_pnl_total == pytest.approx(result["trade"].net_pnl)


# ---- close_position (standalone primitive) -----------------------------


async def test_close_position_full_close():
    position = _open_position(side="LONG", quantity=0.1, entry_price=100_000.0)
    account = _account()
    session_factory, session = _orders_session(account=account, position_get=position)

    with patch("app.services.futures_sim.orders.get_current_price", _price(102_000.0)):
        trade = await close_position(account, session_factory, AsyncMock(), position_id=position.id)

    assert trade.quantity == pytest.approx(0.1)
    assert position.status == "CLOSED"


async def test_close_position_partial_close_by_quantity():
    position = _open_position(side="LONG", quantity=0.2, entry_price=100_000.0)
    account = _account()
    session_factory, session = _orders_session(account=account, position_get=position)

    with patch("app.services.futures_sim.orders.get_current_price", _price(102_000.0)):
        trade = await close_position(
            account, session_factory, AsyncMock(), position_id=position.id, quantity=0.05
        )

    assert trade.quantity == pytest.approx(0.05)
    assert position.status == "OPEN"
    assert position.quantity == pytest.approx(0.15)


async def test_close_position_uses_the_exit_reason_passed_in():
    position = _open_position(side="SHORT", quantity=0.1, entry_price=100_000.0)
    account = _account()
    session_factory, session = _orders_session(account=account, position_get=position)

    with patch("app.services.futures_sim.orders.get_current_price", _price(90_000.0)):
        trade = await close_position(
            account,
            session_factory,
            AsyncMock(),
            position_id=position.id,
            exit_reason="LIQUIDATION",
        )

    assert trade.exit_reason == "LIQUIDATION"
    assert position.close_reason == "LIQUIDATION"


async def test_close_position_persists_realized_pnl_on_the_session_bound_account():
    position = _open_position(side="LONG", quantity=0.1, entry_price=100_000.0)
    detached_account = _account()
    session_bound_account = _account()
    session_factory, session = _orders_session(account=session_bound_account, position_get=position)

    with patch("app.services.futures_sim.orders.get_current_price", _price(102_000.0)):
        trade = await close_position(
            detached_account, session_factory, AsyncMock(), position_id=position.id
        )

    assert detached_account.wallet_balance == 10_000.0
    assert session_bound_account.wallet_balance == pytest.approx(10_000.0 + trade.net_pnl)


async def test_close_position_rejects_when_position_not_open():
    account = _account()
    session_factory, session = _orders_session(account=account, position_get=None)
    with pytest.raises(OrderRejected, match="No open position"):
        await close_position(account, session_factory, AsyncMock(), position_id=999)


async def test_close_position_rejects_when_position_belongs_to_another_account():
    position = _open_position(side="LONG", quantity=0.1)
    position.account_id = 2
    account = _account(id=1)
    session_factory, session = _orders_session(account=account, position_get=position)
    with pytest.raises(OrderRejected, match="No open position"):
        await close_position(account, session_factory, AsyncMock(), position_id=position.id)


async def test_close_position_rejects_quantity_exceeding_position_size():
    position = _open_position(side="LONG", quantity=0.1)
    position.account_id = 1
    account = _account(id=1)
    session_factory, session = _orders_session(account=account, position_get=position)
    with (
        patch("app.services.futures_sim.orders.get_current_price", _price(100_000.0)),
        pytest.raises(OrderRejected, match="quantity must be between"),
    ):
        await close_position(
            account, session_factory, AsyncMock(), position_id=position.id, quantity=1.0
        )


async def test_close_position_rejects_when_no_market_data():
    position = _open_position(side="LONG", quantity=0.1)
    position.account_id = 1
    account = _account(id=1)
    session_factory, session = _orders_session(account=account, position_get=position)
    with (
        patch("app.services.futures_sim.orders.get_current_price", AsyncMock(return_value=None)),
        pytest.raises(OrderRejected, match="No market data available"),
    ):
        await close_position(account, session_factory, AsyncMock(), position_id=position.id)


# ---- set_stop_loss_take_profit -----------------------------------------


async def test_set_stop_loss_take_profit_sets_both_prices():
    position = _open_position(side="LONG", entry_price=100_000.0)
    account = _account()
    session_factory, session = _orders_session(account=account, position_get=position)

    result = await set_stop_loss_take_profit(
        account, session_factory, position_id=position.id, sl_price=95_000.0, tp_price=110_000.0
    )

    assert result.sl_price == 95_000.0
    assert result.tp_price == 110_000.0


async def test_set_stop_loss_take_profit_clears_a_trigger_with_none():
    position = _open_position(side="LONG", entry_price=100_000.0, sl_price=95_000.0)
    account = _account()
    session_factory, session = _orders_session(account=account, position_get=position)

    result = await set_stop_loss_take_profit(
        account, session_factory, position_id=position.id, sl_price=None, tp_price=None
    )

    assert result.sl_price is None
    assert result.tp_price is None


async def test_set_stop_loss_rejects_long_sl_above_entry():
    position = _open_position(side="LONG", entry_price=100_000.0)
    account = _account()
    session_factory, session = _orders_session(account=account, position_get=position)
    with pytest.raises(OrderRejected, match="stop-loss for a LONG"):
        await set_stop_loss_take_profit(
            account, session_factory, position_id=position.id, sl_price=101_000.0, tp_price=None
        )


async def test_set_take_profit_rejects_long_tp_below_entry():
    position = _open_position(side="LONG", entry_price=100_000.0)
    account = _account()
    session_factory, session = _orders_session(account=account, position_get=position)
    with pytest.raises(OrderRejected, match="take-profit for a LONG"):
        await set_stop_loss_take_profit(
            account, session_factory, position_id=position.id, sl_price=None, tp_price=99_000.0
        )


async def test_set_stop_loss_rejects_short_sl_below_entry():
    position = _open_position(side="SHORT", entry_price=100_000.0)
    account = _account()
    session_factory, session = _orders_session(account=account, position_get=position)
    with pytest.raises(OrderRejected, match="stop-loss for a SHORT"):
        await set_stop_loss_take_profit(
            account, session_factory, position_id=position.id, sl_price=99_000.0, tp_price=None
        )


async def test_set_take_profit_rejects_short_tp_above_entry():
    position = _open_position(side="SHORT", entry_price=100_000.0)
    account = _account()
    session_factory, session = _orders_session(account=account, position_get=position)
    with pytest.raises(OrderRejected, match="take-profit for a SHORT"):
        await set_stop_loss_take_profit(
            account, session_factory, position_id=position.id, sl_price=None, tp_price=101_000.0
        )


async def test_set_stop_loss_take_profit_rejects_when_position_not_open():
    account = _account()
    session_factory, session = _orders_session(account=account, position_get=None)
    with pytest.raises(OrderRejected, match="No open position"):
        await set_stop_loss_take_profit(
            account, session_factory, position_id=999, sl_price=95_000.0, tp_price=None
        )


# ---- place_limit_order --------------------------------------------------


async def test_place_limit_order_creates_a_resting_new_order():
    account = _account()
    session_factory, session = _orders_session(scalar_side_effect=[None])

    result = await place_limit_order(
        account,
        session_factory,
        AsyncMock(),
        symbol="BTC",
        side="BUY",
        quantity=0.1,
        leverage=20,
        price=90_000.0,
    )

    order = result["order"]
    assert order.status == "NEW"
    assert order.order_type == "LIMIT"
    assert order.price == 90_000.0
    assert result["idempotent_replay"] is False
    session.commit.assert_awaited()


async def test_place_limit_order_is_idempotent_on_duplicate_client_order_id():
    existing = SimpleNamespace(id=1, client_order_id="abc")
    session_factory, session = _orders_session(scalar_side_effect=[existing])

    result = await place_limit_order(
        _account(),
        session_factory,
        AsyncMock(),
        symbol="BTC",
        side="BUY",
        quantity=0.1,
        leverage=20,
        price=90_000.0,
        client_order_id="abc",
    )

    assert result["idempotent_replay"] is True
    assert result["order"] is existing


async def test_place_limit_order_rejects_non_positive_price():
    session_factory, _ = _orders_session(scalar_side_effect=[None])
    with pytest.raises(OrderRejected, match="price must be positive"):
        await place_limit_order(
            _account(),
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="BUY",
            quantity=0.1,
            leverage=20,
            price=0,
        )


# ---- place_stop_order ----------------------------------------------------


async def test_place_stop_order_creates_a_resting_new_order():
    account = _account()
    session_factory, session = _orders_session(scalar_side_effect=[None])

    result = await place_stop_order(
        account,
        session_factory,
        AsyncMock(),
        symbol="BTC",
        side="SELL",
        quantity=0.1,
        leverage=20,
        stop_price=70_000.0,
        order_type="STOP_MARKET",
    )

    order = result["order"]
    assert order.status == "NEW"
    assert order.order_type == "STOP_MARKET"
    assert order.stop_price == 70_000.0


async def test_place_stop_order_rejects_invalid_order_type():
    session_factory, _ = _orders_session(scalar_side_effect=[None])
    with pytest.raises(OrderRejected, match="STOP_MARKET or TAKE_PROFIT_MARKET"):
        await place_stop_order(
            _account(),
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="SELL",
            quantity=0.1,
            leverage=20,
            stop_price=70_000.0,
            order_type="TRAILING_STOP",
        )


# ---- cancel_order ---------------------------------------------------------


async def test_cancel_order_cancels_a_resting_new_order():
    account = _account()
    order = SimpleNamespace(id=1, account_id=1, status="NEW", cancelled_at=None)
    session_factory, session = _orders_session(account=account, order_get=order)

    result = await cancel_order(account, session_factory, order_id=1)

    assert result.status == "CANCELLED"
    assert result.cancelled_at is not None


async def test_cancel_order_rejects_when_order_not_found():
    account = _account()
    session_factory, session = _orders_session(account=account, order_get=None)
    with pytest.raises(OrderRejected, match="No order"):
        await cancel_order(account, session_factory, order_id=999)


async def test_cancel_order_rejects_when_order_belongs_to_another_account():
    account = _account(id=1)
    order = SimpleNamespace(id=1, account_id=2, status="NEW", cancelled_at=None)
    session_factory, session = _orders_session(account=account, order_get=order)
    with pytest.raises(OrderRejected, match="No order"):
        await cancel_order(account, session_factory, order_id=1)


async def test_cancel_order_rejects_an_already_filled_order():
    account = _account(id=1)
    order = SimpleNamespace(id=1, account_id=1, status="FILLED", cancelled_at=None)
    session_factory, session = _orders_session(account=account, order_get=order)
    with pytest.raises(OrderRejected, match="not cancellable"):
        await cancel_order(account, session_factory, order_id=1)
