from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.analysis.correlation import (
    CorrelationEngine,
    compute_correlation,
    compute_correlation_strength,
)


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


# ---- Data Leakage Protection (Phase 23): as_of bounding ---------------------


def _build_correlation_engine():
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=None)
    session.__aenter__.return_value = session
    session_factory = MagicMock(return_value=session)
    return CorrelationEngine(session_factory, pairs=(("BTC", "DXY"),), windows_days=(30,)), session


async def test_get_latest_bounds_every_pair_query_when_as_of_is_given():
    # Forecasting 2.0: a forecast's own reference_timestamp must bound
    # every pair/window read so nothing calculated after the fact can
    # leak into a re-graded or backfilled forecast's confidence breakdown.
    engine, session = _build_correlation_engine()
    cutoff = datetime(2026, 8, 1, tzinfo=UTC)

    await engine.get_latest(as_of=cutoff)

    query = session.scalar.call_args[0][0]
    compiled = str(query.compile(compile_kwargs={"literal_binds": True}))
    assert "calculated_at <=" in compiled
    assert "2026-08-01" in compiled


async def test_get_latest_unbounded_when_as_of_is_none():
    engine, session = _build_correlation_engine()

    await engine.get_latest()

    query = session.scalar.call_args[0][0]
    compiled = str(query.compile())
    assert "calculated_at <=" not in compiled
