from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.futures_sim.engine import (
    LEVERAGE_OPTIONS,
    FuturesSimEngine,
    available_leverage_options,
    compute_cross_liquidation_price,
    compute_fee,
    compute_initial_margin,
    compute_isolated_liquidation_price,
    compute_maintenance_margin,
    compute_market_fill_price,
    compute_net_pnl,
    compute_position_pnl,
    compute_roi_pct,
    compute_simulated_mark_price,
    get_current_price,
    resolve_max_leverage,
    validate_leverage,
)

# ---- Leverage brackets -------------------------------------------------


def test_resolve_max_leverage_uses_the_symbol_bracket():
    assert resolve_max_leverage("BTC") == 75
    assert resolve_max_leverage("SUI") == 20


def test_resolve_max_leverage_falls_back_to_configured_default_for_unknown_symbol():
    assert resolve_max_leverage("DOTUSDT_MADE_UP") == 20  # futures_sim_default_max_leverage


def test_available_leverage_options_clamps_to_the_symbol_bracket():
    sui_options = available_leverage_options("SUI")
    assert sui_options == [lev for lev in LEVERAGE_OPTIONS if lev <= 20]
    assert 75 not in sui_options
    btc_options = available_leverage_options("BTC")
    assert 75 in btc_options


def test_validate_leverage_accepts_a_valid_option_within_bracket():
    assert validate_leverage("BTC", 50) == 50


def test_validate_leverage_rejects_a_non_standard_leverage_value():
    with pytest.raises(ValueError, match="not a supported leverage option"):
        validate_leverage("BTC", 40)


def test_validate_leverage_rejects_leverage_above_the_symbol_bracket():
    with pytest.raises(ValueError, match="max leverage is 20x"):
        validate_leverage("SUI", 75)


# ---- Margin / PnL / ROI -------------------------------------------------


def test_compute_initial_margin_is_notional_over_leverage():
    assert compute_initial_margin(10_000, 20) == 500.0


def test_compute_maintenance_margin_is_a_pct_of_notional():
    assert compute_maintenance_margin(10_000, 0.4) == 40.0


def test_compute_position_pnl_long_profit_and_loss():
    assert compute_position_pnl("LONG", 100_000, 102_000, 0.1) == pytest.approx(200.0)
    assert compute_position_pnl("LONG", 100_000, 98_000, 0.1) == pytest.approx(-200.0)


def test_compute_position_pnl_short_profit_and_loss():
    assert compute_position_pnl("SHORT", 100_000, 98_000, 0.1) == pytest.approx(200.0)
    assert compute_position_pnl("SHORT", 100_000, 102_000, 0.1) == pytest.approx(-200.0)


def test_compute_position_pnl_rejects_an_invalid_side():
    with pytest.raises(ValueError, match="side must be LONG or SHORT"):
        compute_position_pnl("SIDEWAYS", 100, 100, 1)


def test_compute_net_pnl_subtracts_every_cost():
    assert compute_net_pnl(
        gross_pnl=200.0, fees=4.0, funding=1.0, slippage_cost=0.5
    ) == pytest.approx(194.5)


def test_compute_roi_pct_matches_the_tasks_own_worked_example():
    # "Margin = $500, Gross PnL = +$100, ROI = +20%"
    assert compute_roi_pct(100.0, 500.0) == 20.0


def test_compute_roi_pct_is_none_when_margin_is_zero():
    assert compute_roi_pct(100.0, 0.0) is None


# ---- Liquidation ----------------------------------------------------------


def test_compute_isolated_liquidation_price_long_is_below_entry():
    liq = compute_isolated_liquidation_price("LONG", 100_000, 20, 0.4)
    # 100000 * (1 - 1/20 + 0.004) = 100000 * 0.954 = 95400
    assert liq == pytest.approx(95_400.0)
    assert liq < 100_000


def test_compute_isolated_liquidation_price_short_is_above_entry():
    liq = compute_isolated_liquidation_price("SHORT", 100_000, 20, 0.4)
    # 100000 * (1 + 1/20 - 0.004) = 100000 * 1.046 = 104600
    assert liq == pytest.approx(104_600.0)
    assert liq > 100_000


def test_compute_isolated_liquidation_price_higher_leverage_liquidates_sooner():
    liq_10x = compute_isolated_liquidation_price("LONG", 100_000, 10, 0.4)
    liq_50x = compute_isolated_liquidation_price("LONG", 100_000, 50, 0.4)
    # higher leverage -> less cushion -> liquidation price closer to entry
    assert liq_50x > liq_10x


def test_compute_cross_liquidation_price_extra_equity_gives_more_cushion():
    entry, quantity = 100_000, 0.1
    initial_margin = compute_initial_margin(entry * quantity, 20)  # 500
    maintenance_margin = compute_maintenance_margin(entry * quantity, 0.4)  # 40
    liq_no_extra = compute_cross_liquidation_price(
        "LONG", entry, quantity, initial_margin, maintenance_margin, other_account_equity=0.0
    )
    liq_with_extra = compute_cross_liquidation_price(
        "LONG", entry, quantity, initial_margin, maintenance_margin, other_account_equity=5_000.0
    )
    # more cushion from the rest of the account -> liquidates further away (lower) for a LONG
    assert liq_with_extra < liq_no_extra


def test_compute_cross_liquidation_price_negative_other_equity_liquidates_sooner():
    entry, quantity = 100_000, 0.1
    initial_margin = compute_initial_margin(entry * quantity, 20)
    maintenance_margin = compute_maintenance_margin(entry * quantity, 0.4)
    liq_healthy = compute_cross_liquidation_price(
        "LONG", entry, quantity, initial_margin, maintenance_margin, other_account_equity=0.0
    )
    liq_underwater = compute_cross_liquidation_price(
        "LONG", entry, quantity, initial_margin, maintenance_margin, other_account_equity=-2_000.0
    )
    assert liq_underwater > liq_healthy


# ---- Fees / slippage / mark price -----------------------------------------


def test_compute_fee_maker_vs_taker_uses_configured_schedule():
    maker = compute_fee(10_000, is_maker=True)
    taker = compute_fee(10_000, is_maker=False)
    assert maker["fee_rate_pct"] == 0.02
    assert maker["fee_amount"] == pytest.approx(2.0)
    assert taker["fee_rate_pct"] == 0.04
    assert taker["fee_amount"] == pytest.approx(4.0)


def test_compute_market_fill_price_buy_pays_more_than_reference():
    fill = compute_market_fill_price("BUY", 100_000)
    assert fill["actual_fill_price"] > fill["requested_price"]
    assert fill["requested_price"] == 100_000
    assert fill["slippage_pct"] == 0.02


def test_compute_market_fill_price_sell_receives_less_than_reference():
    fill = compute_market_fill_price("SELL", 100_000)
    assert fill["actual_fill_price"] < fill["requested_price"]


def test_compute_simulated_mark_price_none_without_any_prices():
    assert compute_simulated_mark_price([]) is None


def test_compute_simulated_mark_price_is_an_ema_not_just_the_last_price():
    prices = [100.0, 100.0, 110.0]
    mark = compute_simulated_mark_price(prices, alpha=0.5)
    # EMA: start=100, after 100 -> 100, after 110 -> 0.5*110+0.5*100=105
    assert mark == pytest.approx(105.0)
    assert mark != prices[-1]  # deliberately distinct from raw last price


def test_compute_simulated_mark_price_single_price_returns_it_unchanged():
    assert compute_simulated_mark_price([123.45]) == 123.45


# ---- get_current_price ----------------------------------------------------


async def test_get_current_price_prefers_a_fresh_realtime_tick():
    tick = SimpleNamespace(price=101.0, event_timestamp=datetime.now(UTC), source="coinbase")
    with patch(
        "app.services.futures_sim.engine.get_latest_ticks",
        AsyncMock(return_value={"BTC": tick}),
    ):
        result = await get_current_price(MagicMock(), AsyncMock(), "BTC")
    assert result["price"] == 101.0
    assert result["source_provider"] == "coinbase"
    assert result["freshness"] == "live"


async def test_get_current_price_falls_back_to_history_when_tick_is_stale():
    stale_tick = SimpleNamespace(
        price=101.0, event_timestamp=datetime.now(UTC) - timedelta(days=2), source="coinbase"
    )
    history_row = SimpleNamespace(close=99.5, timestamp=datetime.now(UTC) - timedelta(hours=1))
    with (
        patch(
            "app.services.futures_sim.engine.get_latest_ticks",
            AsyncMock(return_value={"BTC": stale_tick}),
        ),
        patch(
            "app.services.futures_sim.engine.find_symbol_config",
            return_value=SimpleNamespace(model=object(), provider=SimpleNamespace()),
        ),
        patch(
            "app.services.futures_sim.engine.get_series",
            AsyncMock(return_value=[history_row]),
        ),
    ):
        result = await get_current_price(MagicMock(), AsyncMock(), "BTC")
    assert result["price"] == 99.5
    assert "history" in result["source_provider"]


async def test_get_current_price_none_when_nothing_is_available():
    with (
        patch("app.services.futures_sim.engine.get_latest_ticks", AsyncMock(return_value={})),
        patch("app.services.futures_sim.engine.find_symbol_config", return_value=None),
    ):
        result = await get_current_price(MagicMock(), AsyncMock(), "MADEUP")
    assert result is None


# ---- Account lifecycle ------------------------------------------------


def _futures_sim_session(scalar_return=None, get_return=None):
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=scalar_return)
    session.scalars = AsyncMock(return_value=[])
    session.add = MagicMock()  # Session.add is sync in real SQLAlchemy, never awaited
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.get = AsyncMock(return_value=get_return)
    session.__aenter__.return_value = session
    return MagicMock(return_value=session), session


async def test_get_or_create_account_creates_a_new_account_with_initial_balance():
    session_factory, session = _futures_sim_session(scalar_return=None)
    engine = FuturesSimEngine(session_factory, AsyncMock())

    account = await engine.get_or_create_account("default")

    assert account.wallet_balance == 10_000.0
    assert account.peak_equity == 10_000.0
    assert account.status == "ACTIVE"
    # one INSERT for the account row, one for the DEPOSIT ledger entry
    assert session.add.call_count == 2
    session.commit.assert_awaited()


async def test_get_or_create_account_is_idempotent_when_one_already_exists():
    existing = SimpleNamespace(id=1, name="default", wallet_balance=8_500.0, status="ACTIVE")
    session_factory, session = _futures_sim_session(scalar_return=existing)
    engine = FuturesSimEngine(session_factory, AsyncMock())

    account = await engine.get_or_create_account("default")

    assert account is existing
    session.add.assert_not_called()  # no new row -- the existing account is reused


async def test_reset_account_marks_old_account_reset_and_creates_a_fresh_one():
    old_account = SimpleNamespace(
        id=1, name="default", wallet_balance=3_200.0, status="ACTIVE", reset_at=None
    )
    session_factory, session = _futures_sim_session(scalar_return=old_account)
    engine = FuturesSimEngine(session_factory, AsyncMock())

    new_account = await engine.reset_account("default")

    assert old_account.status == "RESET"
    assert old_account.reset_at is not None
    assert new_account.wallet_balance == 10_000.0
    assert new_account.status == "ACTIVE"
    # RESET ledger entry (old) + new DEPOSIT ledger entry (new) + new account row
    assert session.add.call_count == 3


async def test_get_account_state_with_no_open_positions_equals_wallet_balance():
    account = SimpleNamespace(
        id=1,
        name="default",
        account_session_id="11111111-1111-1111-1111-111111111111",
        status="ACTIVE",
        wallet_balance=10_000.0,
        realized_pnl_total=0.0,
        fees_paid_total=0.0,
        funding_paid_total=0.0,
        peak_equity=10_000.0,
        max_drawdown_pct=0.0,
        created_at=datetime.now(UTC),
        reset_at=None,
    )
    session_factory, session = _futures_sim_session()
    session.scalars = AsyncMock(return_value=[])  # no open positions
    engine = FuturesSimEngine(session_factory, AsyncMock())

    state = await engine.get_account_state(account)

    assert state["wallet_balance"] == 10_000.0
    assert state["equity"] == 10_000.0
    assert state["unrealized_pnl"] == 0.0
    assert state["used_margin"] == 0.0
    assert state["available_margin"] == 10_000.0
    assert state["open_position_count"] == 0


async def test_get_account_state_includes_open_position_unrealized_pnl():
    account = SimpleNamespace(
        id=1,
        name="default",
        account_session_id="11111111-1111-1111-1111-111111111111",
        status="ACTIVE",
        wallet_balance=9_500.0,
        realized_pnl_total=0.0,
        fees_paid_total=0.0,
        funding_paid_total=0.0,
        peak_equity=10_000.0,
        max_drawdown_pct=0.0,
        created_at=datetime.now(UTC),
        reset_at=None,
    )
    open_position = SimpleNamespace(
        symbol="BTC",
        side="LONG",
        entry_price=100_000.0,
        mark_price=100_000.0,
        quantity=0.1,
        initial_margin=500.0,
        maintenance_margin=40.0,
    )
    session_factory, session = _futures_sim_session(get_return=account)
    session.scalars = AsyncMock(return_value=[open_position])
    engine = FuturesSimEngine(session_factory, AsyncMock())

    tick = SimpleNamespace(price=102_000.0, event_timestamp=datetime.now(UTC), source="coinbase")
    with patch(
        "app.services.futures_sim.engine.get_latest_ticks", AsyncMock(return_value={"BTC": tick})
    ):
        state = await engine.get_account_state(account)

    assert state["unrealized_pnl"] == pytest.approx(200.0)  # (102000-100000)*0.1
    assert state["used_margin"] == 500.0
    assert state["equity"] == pytest.approx(9_700.0)
    assert state["open_position_count"] == 1
