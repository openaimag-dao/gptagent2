from app.services.analysis.correlation import compute_correlation


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
