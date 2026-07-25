from app.services.portfolio.analytics import (
    compute_diversification_score,
    compute_exposure,
    compute_health_score,
    compute_risk_score,
    unrealized_pnl_pct,
    value_position,
)


def test_value_position():
    assert value_position(2.0, 100.0) == 200.0


def test_unrealized_pnl_pct_none_without_entry_price():
    assert unrealized_pnl_pct(None, 100.0) is None


def test_unrealized_pnl_pct_computes_gain():
    assert unrealized_pnl_pct(50.0, 100.0) == 100.0


def test_compute_exposure_normalizes_to_100():
    exposure = compute_exposure({"crypto": 60.0, "stock": 40.0})
    assert exposure == {"crypto": 60.0, "stock": 40.0}
    assert sum(exposure.values()) == 100.0


def test_compute_exposure_empty_when_zero_total():
    assert compute_exposure({}) == {}
    assert compute_exposure({"crypto": 0.0}) == {}


def test_diversification_score_high_when_evenly_spread():
    score = compute_diversification_score(
        {"crypto": 25.0, "stock": 25.0, "macro": 25.0, "cash": 25.0}
    )
    assert score > 70


def test_diversification_score_zero_when_fully_concentrated():
    score = compute_diversification_score({"crypto": 100.0})
    assert score == 0


def test_diversification_score_none_when_no_exposure():
    assert compute_diversification_score({}) is None


def test_risk_score_high_for_small_drawdown():
    assert compute_risk_score(2.0) > 90


def test_risk_score_zero_for_large_drawdown():
    assert compute_risk_score(60.0) == 0


def test_risk_score_none_when_unavailable():
    assert compute_risk_score(None) is None


def test_health_score_uses_only_available_components():
    score = compute_health_score(100.0, None, None)
    assert score == 100


def test_health_score_blends_all_components():
    score = compute_health_score(100.0, 80.0, 60.0)
    assert 60 < score < 100
