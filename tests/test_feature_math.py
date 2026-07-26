from app.services.features.math import (
    compute_beta,
    compute_cointegration,
    compute_market_breadth,
    compute_momentum_delta,
    compute_returns,
    compute_rolling_momentum,
    dickey_fuller_test,
)


def test_compute_returns_basic():
    assert compute_returns([100, 110, 99]) == [0.1, -0.1]


def test_compute_returns_empty_and_single():
    assert compute_returns([]) == []
    assert compute_returns([100]) == []


def test_rolling_momentum_none_when_not_enough_history():
    assert compute_rolling_momentum([100, 101, 102], window=5) is None


def test_rolling_momentum_computes_pct_change_over_window():
    closes = [100, 105, 110, 121]
    assert compute_rolling_momentum(closes, window=3) == 21.0


def test_beta_none_below_two_points():
    assert compute_beta([0.01], [0.02]) is None


def test_beta_of_asset_vs_itself_is_one():
    returns = [0.01, -0.02, 0.03, -0.01, 0.02]
    assert compute_beta(returns, returns) == 1.0


def test_beta_zero_when_asset_uncorrelated_with_constant_benchmark():
    assert compute_beta([0.01, -0.02, 0.03], [0.0, 0.0, 0.0]) is None


def test_market_breadth_none_when_empty():
    assert compute_market_breadth([]) is None


def test_market_breadth_all_positive():
    assert compute_market_breadth([1.0, 2.0, 3.0]) == 100.0


def test_market_breadth_mixed():
    assert compute_market_breadth([1.0, -1.0, 2.0, -2.0]) == 50.0


def test_momentum_delta_none_below_two_points():
    assert compute_momentum_delta([1.0]) is None


def test_momentum_delta_positive_change():
    assert compute_momentum_delta([0.01, 0.02]) == 100.0


def test_momentum_delta_handles_negative_funding_rates():
    assert compute_momentum_delta([-0.01, -0.02]) == -100.0


def test_dickey_fuller_none_below_three_points():
    assert dickey_fuller_test([1.0, 2.0]) is None


def test_dickey_fuller_detects_oscillating_series_as_stationary():
    series = [0, 1, 0, 1, 0, 1, 0, 1, 0, 1] * 3
    result = dickey_fuller_test([float(v) for v in series])
    assert result is not None
    assert result["is_stationary"] is True


def test_dickey_fuller_detects_pure_random_walk_as_non_stationary():
    # A strictly monotonic ramp has no y_{t-1} -> delta_y relationship at all
    # (delta_y is constant), which is exactly the unit-root null case.
    series = [float(i) for i in range(30)]
    result = dickey_fuller_test(series)
    assert result is not None
    assert result["is_stationary"] is False


def test_cointegration_none_below_five_points():
    assert compute_cointegration([1.0, 2.0], [1.0, 2.0]) is None


def test_cointegration_mean_reverting_spread_is_stationary():
    b = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 109.0, 108.0]
    noise = [0.0, 2.0, -2.0, 2.0, -2.0, 2.0, -2.0, 2.0, -2.0, 2.0]
    a = [b[i] + noise[i] for i in range(len(b))]
    result = compute_cointegration(a, b)
    assert result is not None
    assert result["is_stationary"] is True


def test_cointegration_two_independent_trending_series_are_not_stationary():
    a = [float(i) for i in range(30)]
    b = [float(i * i) for i in range(30)]
    result = compute_cointegration(a, b)
    assert result is not None
    assert result["is_stationary"] is False
