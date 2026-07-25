from app.services.history.indicators import (
    compute_atr,
    compute_macd,
    compute_moving_averages,
    compute_returns,
    compute_rsi,
    compute_sma,
    compute_volatility,
    compute_volume_change,
)


def test_compute_returns():
    closes = [100.0, 110.0, 99.0, 108.9]
    returns = compute_returns(closes)
    assert returns[0] is None
    assert returns[1] == 0.1
    assert round(returns[2], 4) == -0.1
    assert round(returns[3], 4) == 0.1


def test_compute_volatility_needs_at_least_two_returns():
    returns = [None, 0.1]
    assert compute_volatility(returns)[1] is None


def test_compute_volatility_matches_hand_computed_stddev():
    # returns: 0.1, -0.1, 0.1 -> sample stddev with ddof=1
    returns = [None, 0.1, -0.1, 0.1]
    volatility = compute_volatility(returns, window=14)
    assert volatility[3] is not None
    assert round(volatility[3], 6) == round(0.11547005383792515, 6)


def test_compute_volume_change():
    volumes = [100.0, 150.0, None, 50.0]
    result = compute_volume_change(volumes)
    assert result[0] is None
    assert result[1] == 0.5
    assert result[2] is None
    assert result[3] is None  # previous (None) -> can't compute


def test_compute_sma_none_until_window_filled():
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    sma = compute_sma(closes, window=3)
    assert sma[0] is None
    assert sma[1] is None
    assert sma[2] == 2.0
    assert sma[3] == 3.0
    assert sma[4] == 4.0


def test_compute_moving_averages_returns_requested_windows():
    closes = [float(i) for i in range(1, 25)]
    mas = compute_moving_averages(closes, windows=(5, 10))
    assert set(mas.keys()) == {5, 10}
    assert mas[5][-1] == sum(closes[-5:]) / 5
    assert mas[10][-1] == sum(closes[-10:]) / 10


def test_compute_rsi_all_gains_is_100():
    closes = [float(i) for i in range(1, 20)]  # strictly increasing
    rsi = compute_rsi(closes, window=14)
    assert rsi[:14] == [None] * 14
    assert rsi[14] == 100.0


def test_compute_rsi_all_losses_is_zero():
    closes = [float(i) for i in range(20, 1, -1)]  # strictly decreasing
    rsi = compute_rsi(closes, window=14)
    assert rsi[14] == 0.0


def test_compute_rsi_insufficient_history_is_all_none():
    closes = [1.0, 2.0, 3.0]
    assert compute_rsi(closes, window=14) == [None, None, None]


def test_compute_atr_insufficient_history_is_all_none():
    highs = [1.0, 2.0]
    lows = [0.5, 1.5]
    closes = [0.8, 1.8]
    assert compute_atr(highs, lows, closes, window=14) == [None, None]


def test_compute_atr_first_value_is_average_true_range():
    n = 20
    highs = [10.0 + i for i in range(n)]
    lows = [9.0 + i for i in range(n)]
    closes = [9.5 + i for i in range(n)]
    atr = compute_atr(highs, lows, closes, window=14)
    assert atr[:14] == [None] * 14
    assert atr[14] is not None
    assert atr[14] > 0


def test_compute_macd_shape_and_none_prefix():
    closes = [float(i) for i in range(1, 40)]
    macd_line, signal_line, histogram = compute_macd(closes, fast=12, slow=26, signal=9)
    assert len(macd_line) == len(signal_line) == len(histogram) == len(closes)
    assert macd_line[:25] == [None] * 25
    assert macd_line[25] is not None
    assert signal_line[25] is not None
    assert histogram[25] == macd_line[25] - signal_line[25]


def test_compute_macd_too_short_is_all_none():
    closes = [1.0, 2.0, 3.0]
    macd_line, signal_line, histogram = compute_macd(closes)
    assert macd_line == [None, None, None]
    assert signal_line == [None, None, None]
    assert histogram == [None, None, None]
