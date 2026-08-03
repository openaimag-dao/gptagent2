from types import SimpleNamespace

from app.services.analysis.correlation import compute_correlation, compute_correlation_strength


def test_perfectly_correlated_series():
    closes_a = {"2026-01-01": 100.0, "2026-01-02": 110.0, "2026-01-03": 99.0, "2026-01-04": 120.0}
    closes_b = {"2026-01-01": 50.0, "2026-01-02": 55.0, "2026-01-03": 49.5, "2026-01-04": 60.0}

    result = compute_correlation(closes_a, closes_b)

    assert result is not None
    correlation, sample_size = result
    assert correlation == 1.0
    assert sample_size == 3


def test_perfectly_inverse_series():
    # closes_b's returns are the exact negation of closes_a's returns each day.
    closes_a = {"2026-01-01": 100.0, "2026-01-02": 110.0, "2026-01-03": 99.0, "2026-01-04": 120.0}
    closes_b = {"2026-01-01": 50.0, "2026-01-02": 45.0, "2026-01-03": 49.5, "2026-01-04": 39.0}

    result = compute_correlation(closes_a, closes_b)

    assert result is not None
    correlation, _ = result
    assert correlation == -1.0


def test_insufficient_overlap_returns_none():
    closes_a = {"2026-01-01": 100.0, "2026-01-02": 110.0}
    closes_b = {"2026-01-01": 50.0, "2026-01-03": 49.5}

    assert compute_correlation(closes_a, closes_b) is None


def test_flat_series_returns_none():
    closes_a = {"2026-01-01": 100.0, "2026-01-02": 100.0, "2026-01-03": 100.0, "2026-01-04": 100.0}
    closes_b = {"2026-01-01": 50.0, "2026-01-02": 55.0, "2026-01-03": 49.5, "2026-01-04": 60.0}

    assert compute_correlation(closes_a, closes_b) is None


def _corr(symbol_a, symbol_b, window_days, correlation):
    return SimpleNamespace(
        symbol_a=symbol_a, symbol_b=symbol_b, window_days=window_days, correlation=correlation
    )


def test_correlation_strength_none_when_empty():
    assert compute_correlation_strength([]) is None


def test_correlation_strength_none_when_no_match_at_window():
    correlations = [_corr("BTC", "DXY", 7, 0.5)]
    assert compute_correlation_strength(correlations, window_days=30) is None


def test_correlation_strength_averages_absolute_values_at_30d():
    correlations = [
        _corr("BTC", "NASDAQ", 30, 0.6),
        _corr("BTC", "DXY", 30, -0.4),
        _corr("BTC", "GOLD", 7, 0.9),  # different window, excluded
    ]
    assert compute_correlation_strength(correlations) == 50  # avg(0.6, 0.4) * 100
