from app.services.technical.indicators import (
    compute_adx,
    compute_bollinger_bands,
    compute_cci,
    compute_ema,
    compute_momentum,
    compute_pivot_points,
    compute_roc,
    compute_stochastic_rsi,
    compute_support_resistance,
    compute_vwma,
)


def test_compute_ema_none_before_span():
    result = compute_ema([1.0, 2.0, 3.0], 5)
    assert result == [None, None, None]


def test_compute_ema_converges_toward_price_in_flat_series():
    closes = [100.0] * 30
    result = compute_ema(closes, 10)
    assert result[-1] == 100.0


def test_compute_bollinger_bands_widen_with_volatility():
    flat = [100.0] * 25
    upper_flat, middle_flat, lower_flat = compute_bollinger_bands(flat, window=20)
    assert upper_flat[-1] == middle_flat[-1] == lower_flat[-1] == 100.0

    volatile = [100.0, 110.0, 90.0, 105.0, 95.0] * 5
    upper_vol, middle_vol, lower_vol = compute_bollinger_bands(volatile, window=20)
    assert upper_vol[-1] > middle_vol[-1] > lower_vol[-1]


def test_compute_bollinger_bands_none_before_window():
    upper, middle, lower = compute_bollinger_bands([1.0, 2.0], window=20)
    assert upper == [None, None]
    assert lower == [None, None]


def test_compute_vwma_weights_by_volume():
    closes = [10.0, 20.0]
    volumes = [100.0, 1.0]
    result = compute_vwma(closes, volumes, window=2)
    # Heavily volume-weighted toward the first (cheaper) price.
    assert result[-1] < 15.0


def test_compute_vwma_none_when_volume_missing():
    result = compute_vwma([1.0, 2.0], [10.0, None], window=2)
    assert result[-1] is None


def test_compute_stochastic_rsi_bounded_0_100():
    closes = [100.0 + (i % 5) * (1 if i % 2 == 0 else -1) for i in range(40)]
    result = compute_stochastic_rsi(closes)
    values = [v for v in result if v is not None]
    assert values
    assert all(0.0 <= v <= 100.0 for v in values)


def test_compute_roc_positive_for_rising_series():
    closes = [float(i) for i in range(1, 20)]
    result = compute_roc(closes, window=5)
    assert result[-1] is not None
    assert result[-1] > 0


def test_compute_roc_none_before_window():
    assert compute_roc([1.0, 2.0], window=5) == [None, None]


def test_compute_momentum_matches_price_difference():
    closes = [10.0, 12.0, 15.0, 20.0]
    result = compute_momentum(closes, window=2)
    assert result[2] == 15.0 - 10.0
    assert result[3] == 20.0 - 12.0


def test_compute_cci_positive_when_price_above_average():
    closes = [100.0] * 19 + [120.0]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    result = compute_cci(highs, lows, closes, window=20)
    assert result[-1] is not None
    assert result[-1] > 0


def test_compute_adx_high_for_strong_trend():
    closes = [float(i) for i in range(1, 60)]
    highs = [c + 1 for c in closes]
    lows = [c - 1 for c in closes]
    result = compute_adx(highs, lows, closes, window=14)
    assert result[-1] is not None
    assert result[-1] > 50


def test_compute_adx_none_with_insufficient_history():
    closes = [float(i) for i in range(1, 10)]
    result = compute_adx(closes, closes, closes, window=14)
    assert all(v is None for v in result)


def test_compute_pivot_points_standard_formula():
    pivots = compute_pivot_points(prior_high=110.0, prior_low=90.0, prior_close=100.0)
    assert pivots["pivot"] == 100.0
    assert pivots["r1"] == 110.0
    assert pivots["s1"] == 90.0
    assert pivots["r2"] == 120.0
    assert pivots["s2"] == 80.0


def test_compute_support_resistance_uses_trailing_window():
    highs = [100.0] * 19 + [150.0]
    lows = [50.0] * 19 + [10.0]
    support, resistance = compute_support_resistance(highs, lows, window=20)
    assert support == 10.0
    assert resistance == 150.0


def test_compute_support_resistance_none_before_window():
    support, resistance = compute_support_resistance([1.0], [1.0], window=20)
    assert support is None
    assert resistance is None
