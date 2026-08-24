from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from app.api import futures_sim


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
