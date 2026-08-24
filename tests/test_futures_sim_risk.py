import pytest

from app.services.futures_sim.risk import compute_risk_metrics


def _account_state(**overrides):
    defaults = dict(
        equity=10_000.0,
        available_margin=9_000.0,
        unrealized_pnl=0.0,
        margin_ratio=10.0,
        max_drawdown_pct=1.0,
    )
    defaults.update(overrides)
    return defaults


def _position(**overrides):
    defaults = dict(
        position_id=1,
        symbol="BTC",
        side="LONG",
        quantity=0.1,
        mark_price=100_000.0,
        liquidation_price=95_000.0,
    )
    defaults.update(overrides)
    return defaults


def test_no_positions_returns_zeroed_exposure_and_no_warnings():
    result = compute_risk_metrics(_account_state(), [])
    assert result["total_exposure"] == 0.0
    assert result["open_position_count"] == 0
    assert result["largest_position"] is None
    assert result["warnings"] == []


def test_distance_to_liquidation_for_long_and_short():
    long_pos = _position(side="LONG", mark_price=100_000.0, liquidation_price=95_000.0)
    short_pos = _position(
        position_id=2, side="SHORT", mark_price=100_000.0, liquidation_price=105_000.0
    )
    result = compute_risk_metrics(_account_state(), [long_pos, short_pos])
    long_risk = next(p for p in result["positions"] if p["position_id"] == 1)
    short_risk = next(p for p in result["positions"] if p["position_id"] == 2)
    assert long_risk["distance_to_liquidation_pct"] == pytest.approx(5.0)
    assert short_risk["distance_to_liquidation_pct"] == pytest.approx(5.0)


def test_distance_to_liquidation_is_none_without_a_liquidation_price():
    position = _position(liquidation_price=None)
    result = compute_risk_metrics(_account_state(), [position])
    assert result["positions"][0]["distance_to_liquidation_pct"] is None


def test_concentration_and_largest_position_across_multiple_positions():
    btc = _position(position_id=1, symbol="BTC", quantity=0.1, mark_price=100_000.0)  # $10k
    eth = _position(position_id=2, symbol="ETH", quantity=1.0, mark_price=2_000.0)  # $2k
    result = compute_risk_metrics(_account_state(), [btc, eth])

    assert result["total_exposure"] == pytest.approx(12_000.0)
    btc_risk = next(p for p in result["positions"] if p["symbol"] == "BTC")
    eth_risk = next(p for p in result["positions"] if p["symbol"] == "ETH")
    assert btc_risk["concentration_pct"] == pytest.approx(100 * 10_000 / 12_000, abs=1e-3)
    assert eth_risk["concentration_pct"] == pytest.approx(100 * 2_000 / 12_000, abs=1e-3)
    assert result["largest_position"]["symbol"] == "BTC"


def test_high_risk_warning_fires_above_the_margin_ratio_threshold():
    result = compute_risk_metrics(_account_state(margin_ratio=60.0), [])
    assert any(w["level"] == "HIGH_RISK" for w in result["warnings"])


def test_no_high_risk_warning_below_the_threshold():
    result = compute_risk_metrics(_account_state(margin_ratio=20.0), [])
    assert not any(w["level"] == "HIGH_RISK" for w in result["warnings"])


def test_near_liquidation_warning_fires_within_the_threshold():
    position = _position(mark_price=100_000.0, liquidation_price=97_000.0)  # 3% away
    result = compute_risk_metrics(_account_state(), [position])
    warning = next(w for w in result["warnings"] if w["level"] == "NEAR_LIQUIDATION")
    assert warning["position_id"] == 1


def test_no_near_liquidation_warning_when_comfortably_far():
    position = _position(mark_price=100_000.0, liquidation_price=50_000.0)  # 50% away
    result = compute_risk_metrics(_account_state(), [position])
    assert not any(w["level"] == "NEAR_LIQUIDATION" for w in result["warnings"])


def test_margin_warning_fires_when_available_margin_is_low():
    result = compute_risk_metrics(_account_state(equity=10_000.0, available_margin=500.0), [])
    assert any(w["level"] == "MARGIN_WARNING" for w in result["warnings"])


def test_daily_loss_combines_realized_and_unrealized_pnl():
    result = compute_risk_metrics(
        _account_state(unrealized_pnl=-100.0), [], todays_realized_pnl=-200.0
    )
    assert result["daily_pnl"] == pytest.approx(-300.0)
    assert result["daily_loss_pct"] == pytest.approx(3.0)  # 300/10_000


def test_daily_loss_pct_is_none_when_the_day_is_profitable():
    result = compute_risk_metrics(
        _account_state(unrealized_pnl=100.0), [], todays_realized_pnl=50.0
    )
    assert result["daily_pnl"] == pytest.approx(150.0)
    assert result["daily_loss_pct"] is None


def test_large_daily_loss_triggers_a_high_risk_warning():
    result = compute_risk_metrics(
        _account_state(equity=10_000.0, unrealized_pnl=-600.0), [], todays_realized_pnl=0.0
    )
    assert any(
        w["level"] == "HIGH_RISK" and "loss" in w["message"].lower() for w in result["warnings"]
    )


def test_permissive_by_default_a_healthy_account_has_no_warnings():
    healthy_position = _position(mark_price=100_000.0, liquidation_price=50_000.0)
    result = compute_risk_metrics(_account_state(), [healthy_position])
    assert result["warnings"] == []
