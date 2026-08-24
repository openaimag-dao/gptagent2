"""Futures Simulator -- acceptance scenario (task's own required worked
example): $10,000 starting balance, BTC at $100,000, open LONG
margin=$500 leverage=20x (notional=$10,000), price rises to $102,000,
verify gross PnL is approximately +$200 (minus fees/slippage), verify
wallet balance/realized PnL/fees/trade history/ledger/performance all
reconcile after close, then open a SHORT and verify the opposite-sign
PnL for a symmetric price move, then simulate a liquidation and verify
the auto-close.

Uses the same mocked-session style as the rest of this suite (real
place_market_order/close_position/check_positions_for_triggers/
compute_performance_stats functions, mocked I/O) rather than a live
server, so this is fully repeatable in CI -- the exact same numbers were
also verified live against the real Postgres-backed server during
development (see the PR description)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.database.models import FuturesSimAccount, FuturesSimPosition
from app.services.futures_sim.monitor import check_positions_for_triggers
from app.services.futures_sim.orders import close_position, place_market_order
from app.services.futures_sim.performance import compute_performance_stats


def _acceptance_session(
    scalar_side_effect=None, scalars_return=None, account=None, position_get=None
):
    """Mirrors tests/test_futures_sim_orders.py's own `_orders_session`
    helper -- `session.get` dispatches by model class since it's called
    for multiple purposes across a single order's lifecycle."""

    async def _get(model, _ident):
        if model is FuturesSimAccount:
            return account
        if model is FuturesSimPosition:
            return position_get
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


def _price(value):
    return AsyncMock(return_value={"price": value})


async def test_acceptance_scenario_long_open_and_close_with_full_reconciliation():
    account = SimpleNamespace(
        id=1, wallet_balance=10_000.0, fees_paid_total=0.0, realized_pnl_total=0.0
    )

    # ---- Step 1: open LONG BTC, margin=$500, leverage=20x, notional=$10,000 ----
    session_factory, session = _acceptance_session(scalar_side_effect=[None, None], account=account)
    with patch("app.services.futures_sim.orders.get_current_price", _price(100_000.0)):
        open_result = await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="BUY",
            quantity=0.1,  # notional = 0.1 * 100_000 = $10,000
            leverage=20,
        )

    position = open_result["position"]
    assert position.side == "LONG"
    assert position.quantity == pytest.approx(0.1)
    assert position.initial_margin == pytest.approx(500.13, rel=1e-2)  # ~$500, task's own figure
    assert open_result["order"].status == "FILLED"
    # A real DB flush would apply funding_paid's column default (0) --
    # this in-memory-only object was never actually flushed to a DB in
    # this mocked-session test, so set it explicitly.
    position.funding_paid = 0.0
    position.opened_at = datetime.now(UTC)

    # ---- Step 2: price rises to $102,000, close the full position ----
    session_factory, session = _acceptance_session(
        scalar_side_effect=[None, position, None], account=account
    )
    with patch("app.services.futures_sim.orders.get_current_price", _price(102_000.0)):
        close_result = await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="SELL",
            quantity=0.1,
            leverage=20,
        )

    trade = close_result["trade"]
    assert trade is not None
    # gross PnL is approximately +$200 (task's own worked example), the
    # small shortfall from exactly $200 is slippage on both legs, exactly
    # as the task's own phrasing ("gross PnL ~= +$200 minus fees/
    # funding/slippage") describes.
    assert trade.gross_pnl == pytest.approx(200.0, abs=5.0)
    assert 190.0 < trade.gross_pnl < 200.0
    assert trade.net_pnl < trade.gross_pnl  # fees subtracted
    assert trade.roi_pct > 0  # a winning trade
    assert position.status == "CLOSED"

    # ---- Step 3: wallet balance / realized PnL / fees / ledger reconcile ----
    assert account.realized_pnl_total == pytest.approx(trade.net_pnl)
    # wallet_balance = initial - the OPEN order's own fee (deducted
    # separately, at open time) + the close trade's net_pnl (which
    # already nets out the close order's own fee) -- two fee events
    # across the position's lifecycle, exactly as the ledger records them.
    open_fee = open_result["order"].fee_amount
    assert account.wallet_balance == pytest.approx(10_000.0 - open_fee + trade.net_pnl)
    assert account.fees_paid_total == pytest.approx(open_fee + trade.fees)
    assert account.fees_paid_total > 0
    # every fee/PnL-affecting event wrote its own ledger entry (never
    # silently applied) -- OPEN's own fee, plus the closing REALIZED_PNL
    # and its own separate FEE entry.
    ledger_event_types = [
        call.args[0].event_type
        for call in session.add.call_args_list
        if hasattr(call.args[0], "event_type")
    ]
    assert "REALIZED_PNL" in ledger_event_types
    assert "FEE" in ledger_event_types

    # ---- Step 4: trade history + performance analytics reflect the trade ----
    stats = compute_performance_stats([trade])
    assert stats["overall"]["total_trades"] == 1
    assert stats["overall"]["winning_trades"] == 1
    assert stats["overall"]["total_pnl"] == pytest.approx(trade.net_pnl)
    assert stats["by_side"]["LONG"]["total_trades"] == 1


async def test_acceptance_scenario_short_has_the_opposite_sign_pnl_of_the_symmetric_long():
    """Task: "then open SHORT and verify opposite PnL" -- a SHORT opened
    at the same reference price with the same-magnitude adverse-to-LONG
    price move should show a comparable-magnitude, opposite-sign PnL to
    the LONG scenario above."""
    account = SimpleNamespace(
        id=2, wallet_balance=10_000.0, fees_paid_total=0.0, realized_pnl_total=0.0
    )

    session_factory, session = _acceptance_session(scalar_side_effect=[None, None], account=account)
    with patch("app.services.futures_sim.orders.get_current_price", _price(100_000.0)):
        open_result = await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="SELL",
            quantity=0.1,
            leverage=20,
        )
    position = open_result["position"]
    assert position.side == "SHORT"
    position.funding_paid = 0.0  # see the matching comment in the LONG scenario above
    position.opened_at = datetime.now(UTC)

    # price rises (bad for a SHORT, the mirror of the LONG scenario's
    # favorable rise) -- SHORT should realize a LOSS here, the opposite
    # sign of the LONG's gain for the same-direction price move.
    session_factory, session = _acceptance_session(
        scalar_side_effect=[None, position, None], account=account
    )
    with patch("app.services.futures_sim.orders.get_current_price", _price(102_000.0)):
        close_result = await place_market_order(
            account,
            session_factory,
            AsyncMock(),
            symbol="BTC",
            side="BUY",
            quantity=0.1,
            leverage=20,
        )

    trade = close_result["trade"]
    assert trade.gross_pnl < 0  # opposite sign of the LONG scenario's +$200
    assert trade.gross_pnl == pytest.approx(-200.0, abs=5.0)


async def test_acceptance_scenario_liquidation_auto_closes_the_position():
    """Task: "then simulate a liquidation and verify auto-close." A LONG
    at high leverage whose mark price has fallen to/through its own
    liquidation_price must be auto-closed by the position monitor with
    exit_reason=LIQUIDATION, through the exact same close_position()
    primitive a manual close uses."""
    account_id = 3
    position = SimpleNamespace(
        id=42,
        account_id=account_id,
        symbol="BTC",
        side="LONG",
        margin_mode="ISOLATED",
        leverage=50,
        quantity=0.1,
        entry_price=100_000.0,
        mark_price=100_000.0,
        initial_margin=200.0,
        maintenance_margin=40.0,
        realized_pnl=0.0,
        funding_paid=0.0,
        # per compute_isolated_liquidation_price(LONG, 100_000, 50, 0.4)
        liquidation_price=98_040.0,
        sl_price=None,
        tp_price=None,
        status="OPEN",
        opened_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        closed_at=None,
        close_reason=None,
    )
    account = SimpleNamespace(
        id=account_id, wallet_balance=10_000.0, fees_paid_total=0.0, realized_pnl_total=0.0
    )

    scan_session = AsyncMock()
    scan_session.scalars = AsyncMock(return_value=[position])
    scan_session.__aenter__.return_value = scan_session

    close_session_factory, close_session = _acceptance_session(
        account=account, position_get=position
    )

    session_factory_calls = iter([scan_session])

    async def _account_lookup_session():
        return account

    with (
        patch(
            "app.services.futures_sim.monitor.get_current_price",
            _price(97_000.0),  # below liquidation_price -- must trigger
        ),
        # close_position (called by the monitor) is in orders.py and
        # resolves get_current_price from its own module namespace, not
        # monitor's -- both need patching for the full round trip.
        patch("app.services.futures_sim.orders.get_current_price", _price(97_000.0)),
        patch(
            "app.services.futures_sim.monitor.close_position", wraps=close_position
        ) as real_close,
    ):
        # check_positions_for_triggers itself opens its own sessions via
        # session_factory -- give it one that serves the scan, then hands
        # off to close_position's own session for the actual close.
        def _session_factory():
            try:
                return next(session_factory_calls)
            except StopIteration:
                return close_session_factory()

        closures = await check_positions_for_triggers(
            MagicMock(side_effect=_session_factory), AsyncMock()
        )

    assert len(closures) == 1
    assert closures[0]["exit_reason"] == "LIQUIDATION"
    assert position.status == "CLOSED"
    assert position.close_reason == "LIQUIDATION"
    real_close.assert_awaited_once()
    # a liquidated LONG realizes a loss (mark price well below entry)
    assert closures[0]["net_pnl"] < 0
