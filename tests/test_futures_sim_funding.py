from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.futures_sim.funding import _funding_rate_info, apply_funding_to_open_positions


def _position(**overrides):
    defaults = dict(
        id=1,
        account_id=1,
        symbol="BTC",
        side="LONG",
        quantity=0.1,
        mark_price=100_000.0,
        funding_paid=0.0,
        status="OPEN",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _account(**overrides):
    defaults = dict(id=1, wallet_balance=10_000.0, funding_paid_total=0.0)
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ---- _funding_rate_info -------------------------------------------------


async def test_funding_rate_info_uses_real_rate_when_available():
    with patch("app.services.futures_sim.funding.WhaleIntelligenceEngine") as mock_engine_cls:
        # CoinGecko's own field is already a percentage (verified against
        # its live /derivatives response for Binance BTCUSDT) -- no *100.
        mock_engine_cls.return_value.get_snapshot = AsyncMock(
            return_value={"funding_rate": 0.007731}
        )
        info = await _funding_rate_info("BTC")

    assert info["source"] == "real"
    assert info["label"] == "real"
    assert info["funding_rate_pct"] == pytest.approx(0.007731)


async def test_funding_rate_info_falls_back_to_simulated_when_real_unavailable():
    with patch("app.services.futures_sim.funding.WhaleIntelligenceEngine") as mock_engine_cls:
        mock_engine_cls.return_value.get_snapshot = AsyncMock(return_value={})
        info = await _funding_rate_info("MADEUP")

    assert info["source"] == "simulated"
    assert info["label"] == "SIMULATED"
    assert info["funding_rate_pct"] == 0.01  # futures_sim_simulated_funding_rate_pct default


async def test_funding_rate_info_falls_back_to_simulated_on_provider_error():
    with patch("app.services.futures_sim.funding.WhaleIntelligenceEngine") as mock_engine_cls:
        mock_engine_cls.return_value.get_snapshot = AsyncMock(side_effect=RuntimeError("boom"))
        info = await _funding_rate_info("BTC")

    assert info["source"] == "simulated"


# ---- apply_funding_to_open_positions -------------------------------------


def _funding_session(position_get, account_get):
    session = AsyncMock()
    session.get = AsyncMock(side_effect=[account_get, position_get])
    session.add = MagicMock()  # Session.add is sync in real SQLAlchemy, never awaited
    session.__aenter__.return_value = session
    return session


def _session_factory_sequence(scan_session, per_position_sessions):
    calls = iter([scan_session, *per_position_sessions])
    return MagicMock(side_effect=lambda: next(calls))


async def test_apply_funding_charges_long_position_a_positive_rate():
    position = _position(side="LONG", quantity=0.1, mark_price=100_000.0)
    account = _account(wallet_balance=10_000.0)

    scan_session = AsyncMock()
    scan_session.scalars = AsyncMock(return_value=[position])
    scan_session.__aenter__.return_value = scan_session

    apply_session = _funding_session(position_get=position, account_get=account)
    session_factory = _session_factory_sequence(scan_session, [apply_session])

    with patch(
        "app.services.futures_sim.funding._funding_rate_info",
        AsyncMock(return_value={"funding_rate_pct": 0.05, "source": "real", "label": "real"}),
    ):
        charged = await apply_funding_to_open_positions(session_factory, AsyncMock())

    # notional = 0.1 * 100_000 = 10_000; fee = 10_000 * 0.05 / 100 = 5.0
    assert len(charged) == 1
    assert charged[0]["signed_fee"] == pytest.approx(5.0)
    assert account.wallet_balance == pytest.approx(9_995.0)
    assert account.funding_paid_total == pytest.approx(5.0)
    assert position.funding_paid == pytest.approx(5.0)


async def test_apply_funding_short_position_is_the_mirror_of_long():
    position = _position(side="SHORT", quantity=0.1, mark_price=100_000.0)
    account = _account(wallet_balance=10_000.0)

    scan_session = AsyncMock()
    scan_session.scalars = AsyncMock(return_value=[position])
    scan_session.__aenter__.return_value = scan_session
    apply_session = _funding_session(position_get=position, account_get=account)
    session_factory = _session_factory_sequence(scan_session, [apply_session])

    with patch(
        "app.services.futures_sim.funding._funding_rate_info",
        AsyncMock(return_value={"funding_rate_pct": 0.05, "source": "real", "label": "real"}),
    ):
        charged = await apply_funding_to_open_positions(session_factory, AsyncMock())

    # SHORT receives when LONG pays (positive rate) -- wallet balance goes UP
    assert charged[0]["signed_fee"] == pytest.approx(-5.0)
    assert account.wallet_balance == pytest.approx(10_005.0)


async def test_apply_funding_skips_positions_no_longer_open():
    position = _position(status="OPEN")
    closed_position = _position(status="CLOSED")
    account = _account()

    scan_session = AsyncMock()
    scan_session.scalars = AsyncMock(return_value=[position])
    scan_session.__aenter__.return_value = scan_session
    apply_session = _funding_session(position_get=closed_position, account_get=account)
    session_factory = _session_factory_sequence(scan_session, [apply_session])

    with patch(
        "app.services.futures_sim.funding._funding_rate_info",
        AsyncMock(return_value={"funding_rate_pct": 0.05, "source": "real", "label": "real"}),
    ):
        charged = await apply_funding_to_open_positions(session_factory, AsyncMock())

    assert charged == []


async def test_apply_funding_skips_when_account_missing():
    position = _position()

    scan_session = AsyncMock()
    scan_session.scalars = AsyncMock(return_value=[position])
    scan_session.__aenter__.return_value = scan_session
    apply_session = _funding_session(position_get=position, account_get=None)
    session_factory = _session_factory_sequence(scan_session, [apply_session])

    with patch(
        "app.services.futures_sim.funding._funding_rate_info",
        AsyncMock(return_value={"funding_rate_pct": 0.05, "source": "real", "label": "real"}),
    ):
        charged = await apply_funding_to_open_positions(session_factory, AsyncMock())

    assert charged == []


async def test_apply_funding_reuses_the_same_rate_for_positions_on_the_same_symbol():
    position_a = _position(id=1, symbol="BTC")
    position_b = _position(id=2, symbol="BTC")
    account = _account()

    scan_session = AsyncMock()
    scan_session.scalars = AsyncMock(return_value=[position_a, position_b])
    scan_session.__aenter__.return_value = scan_session
    session_a = _funding_session(position_get=position_a, account_get=account)
    session_b = _funding_session(position_get=position_b, account_get=account)
    session_factory = _session_factory_sequence(scan_session, [session_a, session_b])

    with patch(
        "app.services.futures_sim.funding._funding_rate_info",
        AsyncMock(return_value={"funding_rate_pct": 0.02, "source": "real", "label": "real"}),
    ) as mock_rate:
        await apply_funding_to_open_positions(session_factory, AsyncMock())

    mock_rate.assert_awaited_once()  # only fetched once for both BTC positions
