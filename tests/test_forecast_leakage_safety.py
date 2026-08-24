"""Forecasting 3.0 (Phase 28): historical replay validation -- proves, not
just asserts in a docstring, that every leakage-sensitive naive-baseline/
CRPS pure function ForecastEngine's grading pipeline relies on is provably
insensitive to data that would not yet have existed at grading time.

The property under test throughout this file is TRUNCATION INVARIANCE: for
a fixed reference point, a function's output computed against the full
(eventually-available) history must be byte-for-byte identical to its
output computed against a history truncated to only what was available up
to that reference point. If a function ever "peeked" at future data, this
is exactly the property that would break -- appending or changing rows
after the reference point would silently change an already-computed
result. This is a stronger, directly falsifiable check than reading the
leakage-safety claims already documented in each function's own docstring
(compute_baseline_return_pct, compute_regime_mean_baseline_return_pct,
compute_forward_returns) -- it replays history at two different "known-so-
far" horizons and requires the answer to match exactly.

grade_price_forecasts() itself is exercised the same way at the integration
level: a forecast graded against a history that ends exactly at its horizon
boundary must grade to the identical values as the same forecast graded
against a history extended arbitrarily further into the future -- proving
the real grading pipeline (not just its pure sub-functions in isolation)
never uses data from beyond a forecast's own horizon."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.alert_performance.engine import compute_baseline_return_pct
from app.services.forecast.engine import (
    compute_regime_mean_baseline_return_pct,
    grade_price_forecasts,
)
from app.services.probability.engine import compute_forward_returns

# A deterministic, non-trivial 20-period return series -- not all zeros or a
# repeating pattern, so a leakage bug that averages in later data would
# actually change the result (a degenerate series could accidentally
# produce the same answer either way and mask a real bug).
_RETURNS_20 = [
    0.02, -0.01, 0.03, 0.00, -0.02, 0.04, 0.01, -0.03, 0.02, 0.05,
    -0.01, 0.02, 0.03, -0.04, 0.01, 0.00, 0.02, -0.02, 0.03, 0.01,
]  # fmt: skip


def test_compute_forward_returns_is_truncation_invariant_within_the_horizon():
    # forward[i] for a fixed horizon only ever needs returns[i+1 : i+1+horizon]
    # -- extra rows appended past that window must not change it.
    horizon = 3
    reference_idx = 10
    full = compute_forward_returns(_RETURNS_20, horizon=horizon)
    truncated_series = _RETURNS_20[: reference_idx + 1 + horizon]  # exactly enough, no more
    truncated = compute_forward_returns(truncated_series, horizon=horizon)
    assert full[reference_idx] == truncated[reference_idx]


def test_compute_forward_returns_changes_if_the_leaked_window_actually_changes():
    # Sanity check for the test above: if the window compute_forward_returns
    # DOES read from actually changes, the result must differ -- otherwise
    # the invariance test above would trivially pass even with a real bug.
    horizon = 3
    reference_idx = 10
    mutated = list(_RETURNS_20)
    mutated[reference_idx + 2] = 0.99  # inside the window forward[10] reads
    forward_original = compute_forward_returns(_RETURNS_20, horizon=horizon)
    forward_mutated = compute_forward_returns(mutated, horizon=horizon)
    assert forward_original[reference_idx] != forward_mutated[reference_idx]


def test_compute_baseline_return_pct_ignores_data_appended_after_reference_idx():
    reference_idx = 10
    horizon = 3
    truncated_series = _RETURNS_20[: reference_idx + 1]  # only what's known "at" reference_idx
    result_full = compute_baseline_return_pct(_RETURNS_20, reference_idx, horizon)
    result_truncated = compute_baseline_return_pct(truncated_series, reference_idx, horizon)
    assert result_full == result_truncated
    assert result_full is not None  # the test is meaningless if there's nothing to compare


def test_compute_baseline_return_pct_reacts_to_data_within_its_own_window():
    # Sanity check: mutating a return INSIDE a window the function actually
    # uses must change the result -- proves the invariance test above isn't
    # trivially passing because the function ignores everything.
    reference_idx = 10
    horizon = 3
    mutated = list(_RETURNS_20)
    mutated[3] = 0.99  # inside a leakage-safe window (i=2, i+horizon=5<=10)
    original = compute_baseline_return_pct(_RETURNS_20, reference_idx, horizon)
    changed = compute_baseline_return_pct(mutated, reference_idx, horizon)
    assert original != changed


def test_compute_regime_mean_baseline_return_pct_ignores_data_appended_after_reference_idx():
    reference_idx = 10
    horizon = 3
    regimes = ["risk_on" if i % 2 == 0 else "risk_off" for i in range(len(_RETURNS_20))]
    truncated_returns = _RETURNS_20[: reference_idx + 1]
    truncated_regimes = regimes[: reference_idx + 1]

    result_full = compute_regime_mean_baseline_return_pct(
        _RETURNS_20, regimes, reference_idx, horizon, "risk_on"
    )
    result_truncated = compute_regime_mean_baseline_return_pct(
        truncated_returns, truncated_regimes, reference_idx, horizon, "risk_on"
    )
    assert result_full == result_truncated
    assert result_full is not None


def test_compute_regime_mean_baseline_return_pct_ignores_a_regime_relabeled_after_reference_idx():
    # Even if history AFTER reference_idx were later reclassified into a
    # different regime (e.g. a regime-detection backfill), that must not
    # change a baseline already computed as of reference_idx.
    reference_idx = 10
    horizon = 3
    regimes_a = ["risk_on"] * len(_RETURNS_20)
    regimes_b = list(regimes_a)
    for i in range(reference_idx + 1, len(regimes_b)):
        regimes_b[i] = "risk_off"  # relabel everything AFTER the reference point only

    result_a = compute_regime_mean_baseline_return_pct(
        _RETURNS_20, regimes_a, reference_idx, horizon, "risk_on"
    )
    result_b = compute_regime_mean_baseline_return_pct(
        _RETURNS_20, regimes_b, reference_idx, horizon, "risk_on"
    )
    assert result_a == result_b


# ---- Integration-level replay: the real grading pipeline -------------------


def _forecast_session(scalars_return, get_return=None):
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=scalars_return)
    session.get = AsyncMock(return_value=get_return)
    session.commit = AsyncMock()
    session.__aenter__.return_value = session
    return MagicMock(return_value=session), session


async def _grade_against_history(rows, ungraded, db_row):
    session_factory, _ = _forecast_session([ungraded], db_row)
    with (
        patch("app.services.forecast.engine.get_series", AsyncMock(return_value=rows)),
        patch("app.services.forecast.engine.build_regime_index", AsyncMock(return_value={})),
    ):
        graded = await grade_price_forecasts(session_factory, "BTC", object())
    return graded


async def test_grade_price_forecasts_result_is_identical_regardless_of_future_history_length():
    # Same forecast, same reference candle and horizon -- graded once against
    # a history that ends EXACTLY at the horizon boundary, and once against
    # the same history extended arbitrarily further into the future (extra
    # rows that would not have existed yet at grading time in a real
    # deployment, but do exist in a replay run later). The graded outcome
    # must be byte-for-byte identical either way -- this is the real
    # grading pipeline's own no-lookahead guarantee, not just its pure
    # sub-functions' guarantee in isolation.
    ts0 = datetime(2026, 8, 1, tzinfo=UTC)
    base_rows = [
        SimpleNamespace(timestamp=ts0 - timedelta(days=2), close=95.0, atr=2.0, return_pct=0.02),
        SimpleNamespace(timestamp=ts0 - timedelta(days=1), close=100.0, atr=2.0, return_pct=0.05),
        SimpleNamespace(timestamp=ts0, close=100.0, atr=2.0, return_pct=None),
        SimpleNamespace(
            timestamp=ts0 + timedelta(days=1),
            close=105.0,
            high=105.0,
            low=105.0,
            atr=2.0,
            return_pct=0.05,
        ),
    ]
    # Extra rows an honest deployment could never have seen yet at the
    # moment this forecast's horizon elapsed -- deliberately different
    # values (not a repeat of the pattern above) so a leakage bug that
    # folds them in would visibly change the graded result.
    future_rows = base_rows + [
        SimpleNamespace(
            timestamp=ts0 + timedelta(days=n),
            close=200.0 + 10 * n,
            high=200.0 + 10 * n,
            low=200.0 + 10 * n,
            atr=9.0,
            return_pct=0.5,
        )
        for n in range(2, 6)
    ]

    def make_ungraded():
        return SimpleNamespace(
            id=1,
            reference_timestamp=ts0,
            horizon="24h",
            target_price=103.0,
            current_price=100.0,
            direction="Bullish",
            regime_at_forecast=None,
            p10_pct=0.0,
            p25_pct=2.0,
            p50_pct=4.0,
            p75_pct=6.0,
            p90_pct=8.0,
        )

    def make_db_row():
        return SimpleNamespace(
            realized_price=None,
            error_pct=None,
            direction_correct=None,
            confidence_correct=None,
            evaluated_at=None,
            forecast_status="ACTIVE",
        )

    db_row_at_boundary = make_db_row()
    graded_at_boundary = await _grade_against_history(
        base_rows, make_ungraded(), db_row_at_boundary
    )
    db_row_with_future = make_db_row()
    graded_with_future = await _grade_against_history(
        future_rows, make_ungraded(), db_row_with_future
    )

    assert graded_at_boundary == 1
    assert graded_with_future == 1
    assert db_row_at_boundary.realized_price == db_row_with_future.realized_price
    assert db_row_at_boundary.error_pct == db_row_with_future.error_pct
    assert db_row_at_boundary.direction_correct == db_row_with_future.direction_correct
    assert db_row_at_boundary.zero_return_baseline_error_pct == (
        db_row_with_future.zero_return_baseline_error_pct
    )
    assert db_row_at_boundary.crps_pct == db_row_with_future.crps_pct


async def test_grade_price_forecasts_never_grades_before_its_own_horizon_has_elapsed():
    # The hard boundary case of the same property: with the future rows
    # entirely absent (not just untrusted), grading must not happen at
    # all -- never a partial or guessed grade.
    ts0 = datetime(2026, 8, 1, tzinfo=UTC)
    rows_missing_the_horizon_candle = [
        SimpleNamespace(timestamp=ts0, close=100.0, atr=2.0, return_pct=None),
    ]
    ungraded = SimpleNamespace(id=1, reference_timestamp=ts0, horizon="24h", target_price=103.0)
    db_row = SimpleNamespace(realized_price=None, error_pct=None, evaluated_at=None)

    graded = await _grade_against_history(rows_missing_the_horizon_candle, ungraded, db_row)

    assert graded == 0
    assert db_row.realized_price is None
