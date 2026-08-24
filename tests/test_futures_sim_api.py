from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api import futures_sim
from app.services.futures_sim.orders import OrderRejected


def _account_state(**overrides):
    state = {
        "name": "default",
        "account_session_id": "11111111-1111-1111-1111-111111111111",
        "status": "ACTIVE",
        "wallet_balance": 10_000.0,
        "equity": 10_000.0,
        "available_margin": 10_000.0,
        "used_margin": 0.0,
        "unrealized_pnl": 0.0,
        "realized_pnl_total": 0.0,
        "fees_paid_total": 0.0,
        "funding_paid_total": 0.0,
        "maintenance_margin_total": 0.0,
        "margin_ratio": None,
        "peak_equity": 10_000.0,
        "max_drawdown_pct": 0.0,
        "open_position_count": 0,
        "created_at": datetime(2026, 8, 24, tzinfo=UTC),
        "reset_at": None,
    }
    state.update(overrides)
    return state


async def test_get_account_creates_and_serializes_the_default_account():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = object()
    engine.get_account_state.return_value = _account_state()
    with patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine):
        payload = await futures_sim.get_account()

    engine.get_or_create_account.assert_awaited_once_with("default")
    assert payload["wallet_balance"] == 10_000.0
    assert payload["equity"] == 10_000.0
    # Task requirement: unambiguous demo-trading labeling on every account read
    assert payload["paper_trading"] is True
    assert payload["real_funds_used"] is False


async def test_get_account_serializes_timestamps_as_isoformat_strings():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = object()
    engine.get_account_state.return_value = _account_state(
        reset_at=datetime(2026, 8, 20, tzinfo=UTC)
    )
    with patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine):
        payload = await futures_sim.get_account()

    assert payload["created_at"] == "2026-08-24T00:00:00+00:00"
    assert payload["reset_at"] == "2026-08-20T00:00:00+00:00"


async def test_reset_account_calls_the_engines_reset_not_get_or_create():
    engine = AsyncMock()
    engine.reset_account.return_value = object()
    engine.get_account_state.return_value = _account_state()
    with patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine):
        payload = await futures_sim.reset_account()

    engine.reset_account.assert_awaited_once_with("default")
    engine.get_or_create_account.assert_not_called()
    assert payload["wallet_balance"] == 10_000.0


async def test_get_symbols_returns_the_full_roster_with_leverage_brackets():
    payload = await futures_sim.get_symbols()

    symbols = {row["symbol"] for row in payload["symbols"]}
    assert symbols == {"BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "LINK", "AVAX", "SUI", "UNI"}
    btc_row = next(row for row in payload["symbols"] if row["symbol"] == "BTC")
    assert btc_row["max_leverage"] == 75
    assert 75 in btc_row["leverage_options"]
    assert btc_row["bracket_is_simulated"] is True

    sui_row = next(row for row in payload["symbols"] if row["symbol"] == "SUI")
    assert sui_row["max_leverage"] == 20
    assert 75 not in sui_row["leverage_options"]


# ---- helpers for the order/position/trade/ledger endpoints ----------------


def _fake_order(**overrides):
    defaults = dict(
        id=1,
        client_order_id="abc-123",
        position_id=5,
        symbol="BTC",
        side="BUY",
        position_side="LONG",
        order_type="MARKET",
        margin_mode="ISOLATED",
        leverage=20,
        quantity=0.1,
        price=None,
        stop_price=None,
        reduce_only=False,
        status="FILLED",
        requested_price=100_000.0,
        estimated_fill_price=100_020.0,
        actual_fill_price=100_020.0,
        slippage_pct=0.02,
        filled_quantity=0.1,
        fee_rate_pct=0.04,
        fee_amount=4.0,
        reject_reason=None,
        strategy_tag="manual",
        prediction_id=None,
        created_at=datetime(2026, 8, 24, tzinfo=UTC),
        filled_at=datetime(2026, 8, 24, tzinfo=UTC),
        cancelled_at=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_position(**overrides):
    defaults = dict(
        id=5,
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
        liquidation_price=95_400.0,
        sl_price=None,
        tp_price=None,
        status="OPEN",
        close_reason=None,
        opened_at=datetime(2026, 8, 24, tzinfo=UTC),
        updated_at=datetime(2026, 8, 24, tzinfo=UTC),
        closed_at=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _fake_trade(**overrides):
    defaults = dict(
        id=9,
        position_id=5,
        symbol="BTC",
        side="LONG",
        leverage=20,
        entry_price=100_000.0,
        exit_price=102_000.0,
        quantity=0.1,
        gross_pnl=200.0,
        fees=4.0,
        funding=0.0,
        net_pnl=196.0,
        roi_pct=39.2,
        opened_at=datetime(2026, 8, 24, tzinfo=UTC),
        closed_at=datetime(2026, 8, 24, tzinfo=UTC),
        duration_seconds=60,
        exit_reason="MANUAL",
        strategy_tag="manual",
        prediction_id=None,
        strategy_label=None,
        note=None,
        self_assessment_tags=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _session_ctx(scalars_return=None, get_return=None):
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=scalars_return or [])
    session.get = AsyncMock(return_value=get_return)
    session.__aenter__.return_value = session
    return MagicMock(return_value=session), session


# ---- POST /orders -----------------------------------------------------


async def test_place_order_rejects_an_unsupported_order_type():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    with patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine):
        with pytest.raises(Exception) as exc_info:
            await futures_sim.place_order(
                futures_sim.PlaceOrderRequest(
                    symbol="BTC", side="BUY", order_type="TRAILING_STOP", quantity=0.1, leverage=20
                )
            )
    assert exc_info.value.status_code == 400


async def test_place_order_limit_requires_a_price():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    with patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine):
        with pytest.raises(Exception) as exc_info:
            await futures_sim.place_order(
                futures_sim.PlaceOrderRequest(
                    symbol="BTC", side="BUY", order_type="LIMIT", quantity=0.1, leverage=20
                )
            )
    assert exc_info.value.status_code == 400


async def test_place_order_stop_market_requires_a_stop_price():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    with patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine):
        with pytest.raises(Exception) as exc_info:
            await futures_sim.place_order(
                futures_sim.PlaceOrderRequest(
                    symbol="BTC",
                    side="BUY",
                    order_type="STOP_MARKET",
                    quantity=0.1,
                    leverage=20,
                )
            )
    assert exc_info.value.status_code == 400


async def test_place_order_limit_delegates_to_place_limit_order():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    order = _fake_order(order_type="LIMIT", status="NEW", price=90_000.0)
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch(
            "app.api.futures_sim.place_limit_order",
            AsyncMock(return_value={"order": order, "idempotent_replay": False}),
        ) as mock_place,
    ):
        payload = await futures_sim.place_order(
            futures_sim.PlaceOrderRequest(
                symbol="BTC",
                side="BUY",
                order_type="LIMIT",
                quantity=0.1,
                leverage=20,
                price=90_000.0,
            )
        )

    assert payload["order"]["status"] == "NEW"
    assert payload["position"] is None
    mock_place.assert_awaited_once()
    assert mock_place.call_args.kwargs["price"] == 90_000.0


async def test_place_order_stop_market_delegates_to_place_stop_order():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    order = _fake_order(order_type="STOP_MARKET", status="NEW", stop_price=70_000.0)
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch(
            "app.api.futures_sim.place_stop_order",
            AsyncMock(return_value={"order": order, "idempotent_replay": False}),
        ) as mock_place,
    ):
        payload = await futures_sim.place_order(
            futures_sim.PlaceOrderRequest(
                symbol="BTC",
                side="SELL",
                order_type="STOP_MARKET",
                quantity=0.1,
                leverage=20,
                stop_price=70_000.0,
            )
        )

    assert payload["order"]["status"] == "NEW"
    mock_place.assert_awaited_once()
    assert mock_place.call_args.kwargs["stop_price"] == 70_000.0
    assert mock_place.call_args.kwargs["order_type"] == "STOP_MARKET"


async def test_place_order_delegates_and_serializes_the_result():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    order = _fake_order()
    position = _fake_position()
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch(
            "app.api.futures_sim.place_market_order",
            AsyncMock(
                return_value={
                    "order": order,
                    "position": position,
                    "trade": None,
                    "idempotent_replay": False,
                }
            ),
        ),
    ):
        payload = await futures_sim.place_order(
            futures_sim.PlaceOrderRequest(symbol="BTC", side="BUY", quantity=0.1, leverage=20)
        )

    assert payload["order"]["symbol"] == "BTC"
    assert payload["order"]["fee_amount"] == 4.0
    assert payload["position"]["side"] == "LONG"
    assert payload["trade"] is None
    assert payload["idempotent_replay"] is False


async def test_place_order_turns_order_rejected_into_http_400():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch(
            "app.api.futures_sim.place_market_order",
            AsyncMock(side_effect=OrderRejected("Insufficient margin: need 5, have 1")),
        ),
    ):
        with pytest.raises(Exception) as exc_info:
            await futures_sim.place_order(
                futures_sim.PlaceOrderRequest(symbol="BTC", side="BUY", quantity=0.1, leverage=20)
            )
    assert exc_info.value.status_code == 400
    assert "Insufficient margin" in exc_info.value.detail


# ---- DELETE /orders/{id} ------------------------------------------------


async def test_cancel_order_endpoint_delegates_and_serializes_the_result():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    order = _fake_order(status="CANCELLED", order_type="LIMIT")
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch("app.api.futures_sim.cancel_order", AsyncMock(return_value=order)) as mock_cancel,
    ):
        payload = await futures_sim.cancel_order_endpoint(order_id=1)

    assert payload["order"]["status"] == "CANCELLED"
    mock_cancel.assert_awaited_once()


async def test_cancel_order_endpoint_turns_order_rejected_into_http_400():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch(
            "app.api.futures_sim.cancel_order",
            AsyncMock(side_effect=OrderRejected("Order 1 is FILLED, not cancellable")),
        ),
    ):
        with pytest.raises(Exception) as exc_info:
            await futures_sim.cancel_order_endpoint(order_id=1)
    assert exc_info.value.status_code == 400


# ---- GET /orders --------------------------------------------------------


async def test_get_orders_returns_serialized_order_history():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    session_factory, session = _session_ctx(scalars_return=[_fake_order()])
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch("app.api.futures_sim.get_session_factory", return_value=session_factory),
    ):
        payload = await futures_sim.get_orders(limit=50)

    assert len(payload["orders"]) == 1
    assert payload["orders"][0]["symbol"] == "BTC"
    assert payload["orders"][0]["status"] == "FILLED"


# ---- GET /positions -----------------------------------------------------


async def test_get_positions_enriches_open_positions_with_live_mark_price_and_pnl():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    session_factory, session = _session_ctx(scalars_return=[_fake_position()])
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch("app.api.futures_sim.get_session_factory", return_value=session_factory),
        patch(
            "app.api.futures_sim.get_current_price",
            AsyncMock(return_value={"price": 102_000.0}),
        ),
    ):
        payload = await futures_sim.get_positions()

    row = payload["positions"][0]
    assert row["mark_price"] == 102_000.0
    assert row["unrealized_pnl"] == pytest.approx(200.0)  # (102000-100000)*0.1
    assert row["roi_pct"] == pytest.approx(40.0)  # 200/500 margin


async def test_get_positions_does_not_enrich_closed_positions():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    closed = _fake_position(status="CLOSED", closed_at=datetime(2026, 8, 24, tzinfo=UTC))
    session_factory, session = _session_ctx(scalars_return=[closed])
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch("app.api.futures_sim.get_session_factory", return_value=session_factory),
        patch("app.api.futures_sim.get_current_price") as mock_price,
    ):
        payload = await futures_sim.get_positions(status="ALL")

    mock_price.assert_not_called()
    assert "unrealized_pnl" not in payload["positions"][0]


# ---- POST /positions/{id}/close -----------------------------------------


async def test_close_position_endpoint_with_explicit_quantity():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    trade = _fake_trade()
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch("app.api.futures_sim.close_position", AsyncMock(return_value=trade)) as mock_close,
    ):
        payload = await futures_sim.close_position_endpoint(
            5, futures_sim.ClosePositionRequest(quantity=0.05)
        )

    assert payload["trade"]["trade_id"] == 9
    mock_close.assert_awaited_once()
    assert mock_close.call_args.kwargs["quantity"] == 0.05


async def test_close_position_endpoint_converts_percent_to_quantity():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    session_factory, session = _session_ctx(get_return=_fake_position(quantity=0.2))
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch("app.api.futures_sim.get_session_factory", return_value=session_factory),
        patch(
            "app.api.futures_sim.close_position", AsyncMock(return_value=_fake_trade())
        ) as mock_close,
    ):
        await futures_sim.close_position_endpoint(5, futures_sim.ClosePositionRequest(percent=50))

    assert mock_close.call_args.kwargs["quantity"] == pytest.approx(0.1)  # 50% of 0.2


async def test_close_position_endpoint_turns_order_rejected_into_http_400():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch(
            "app.api.futures_sim.close_position",
            AsyncMock(side_effect=OrderRejected("No open position 5 on this account")),
        ),
    ):
        with pytest.raises(Exception) as exc_info:
            await futures_sim.close_position_endpoint(5, futures_sim.ClosePositionRequest())
    assert exc_info.value.status_code == 400


# ---- GET /trades ----------------------------------------------------------


async def test_get_trades_returns_serialized_trade_history():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    session_factory, session = _session_ctx(scalars_return=[_fake_trade()])
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch("app.api.futures_sim.get_session_factory", return_value=session_factory),
    ):
        payload = await futures_sim.get_trades(limit=50)

    assert len(payload["trades"]) == 1
    assert payload["trades"][0]["net_pnl"] == 196.0


# ---- GET /performance ---------------------------------------------------


async def test_get_performance_returns_overall_and_breakdown_stats():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    session_factory, session = _session_ctx(scalars_return=[_fake_trade()])
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch("app.api.futures_sim.get_session_factory", return_value=session_factory),
    ):
        payload = await futures_sim.get_performance()

    assert payload["overall"]["total_trades"] == 1
    assert payload["overall"]["winning_trades"] == 1
    assert "BTC" in payload["by_symbol"]


async def test_get_performance_with_no_trades_returns_zeroed_stats():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    session_factory, session = _session_ctx(scalars_return=[])
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch("app.api.futures_sim.get_session_factory", return_value=session_factory),
    ):
        payload = await futures_sim.get_performance()

    assert payload["overall"]["total_trades"] == 0
    assert payload["by_symbol"] == {}


# ---- GET /ledger ------------------------------------------------------


async def test_get_ledger_returns_serialized_entries():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    entry = SimpleNamespace(
        id=1,
        event_type="DEPOSIT",
        amount=10_000.0,
        balance_after=10_000.0,
        reference_type="ACCOUNT",
        reference_id=1,
        description="Initial demo balance",
        created_at=datetime(2026, 8, 24, tzinfo=UTC),
    )
    session_factory, session = _session_ctx(scalars_return=[entry])
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch("app.api.futures_sim.get_session_factory", return_value=session_factory),
    ):
        payload = await futures_sim.get_ledger(limit=100)

    assert len(payload["ledger"]) == 1
    assert payload["ledger"][0]["event_type"] == "DEPOSIT"
    assert payload["ledger"][0]["created_at"] == "2026-08-24T00:00:00+00:00"


# ---- POST /positions/{id}/sl-tp -----------------------------------------


async def test_set_position_sl_tp_delegates_and_serializes_the_result():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    position = _fake_position(sl_price=95_000.0, tp_price=110_000.0)
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch(
            "app.api.futures_sim.set_stop_loss_take_profit", AsyncMock(return_value=position)
        ) as mock_set,
    ):
        payload = await futures_sim.set_position_sl_tp(
            5, futures_sim.SetStopLossTakeProfitRequest(sl_price=95_000.0, tp_price=110_000.0)
        )

    assert payload["position"]["sl_price"] == 95_000.0
    assert payload["position"]["tp_price"] == 110_000.0
    assert mock_set.call_args.kwargs["sl_price"] == 95_000.0
    assert mock_set.call_args.kwargs["tp_price"] == 110_000.0


async def test_set_position_sl_tp_turns_order_rejected_into_http_400():
    engine = AsyncMock()
    engine.get_or_create_account.return_value = SimpleNamespace(id=1)
    with (
        patch("app.api.futures_sim.build_futures_sim_engine", return_value=engine),
        patch(
            "app.api.futures_sim.set_stop_loss_take_profit",
            AsyncMock(
                side_effect=OrderRejected("stop-loss for a LONG position must be below entry price")
            ),
        ),
    ):
        with pytest.raises(Exception) as exc_info:
            await futures_sim.set_position_sl_tp(
                5, futures_sim.SetStopLossTakeProfitRequest(sl_price=999_999.0)
            )
    assert exc_info.value.status_code == 400
