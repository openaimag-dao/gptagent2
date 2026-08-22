import pytest

from app.services.probability.engine import (
    compute_forward_return_quantiles,
    compute_forward_returns,
    compute_quantile_coverage,
    compute_quantile_coverage_by_group,
    compute_rsi_probability,
)


def _graded(realized_return_pct, p10=-5.0, p90=5.0, p25=-2.0, p75=2.0, **extra):
    return {
        "realized_return_pct": realized_return_pct,
        "p10_pct": p10,
        "p25_pct": p25,
        "p50_pct": 0.0,
        "p75_pct": p75,
        "p90_pct": p90,
        **extra,
    }


def test_compute_forward_returns_shifts_back_by_horizon():
    returns = [0.01, 0.02, -0.03, 0.04, None]
    forward = compute_forward_returns(returns, horizon=1)
    assert forward[:3] == pytest.approx([0.02, -0.03, 0.04])
    assert forward[3:] == [None, None]


def test_compute_forward_returns_horizon_two_compounds_both_periods():
    returns = [0.01, 0.02, -0.03, 0.04]
    forward = compute_forward_returns(returns, horizon=2)
    # index 0: compound periods 1 and 2 -> (1.02 * 0.97) - 1
    assert forward[0] == pytest.approx((1.02 * 0.97) - 1)
    # index 1: compound periods 2 and 3 -> (0.97 * 1.04) - 1
    assert forward[1] == pytest.approx((0.97 * 1.04) - 1)
    # index 2/3: window runs past the end of the series -> None, not guessed
    assert forward[2] is None
    assert forward[3] is None


def test_compute_forward_returns_none_when_any_period_in_window_missing():
    returns = [0.01, None, 0.03, 0.04]
    forward = compute_forward_returns(returns, horizon=2)
    # index 0's window (periods 1, 2) includes a None -> None, not a partial compound
    assert forward[0] is None


def test_compute_rsi_probability_insufficient_sample_returns_none():
    rsi_series = [50.0, 51.0, 49.0]
    returns_series = [0.01, 0.02, -0.01]
    assert compute_rsi_probability(rsi_series, returns_series, 50.0) is None


def test_compute_rsi_probability_counts_matches_within_bucket():
    # 10 historical points with RSI in [45, 55] (bucket around ref=50, width=10),
    # forward returns alternate positive/negative so we can hand-verify the split.
    rsi_series = [50.0] * 10 + [90.0]  # last point is the "current" candle (excluded, no forward)
    returns_series = [0.01, -0.01] * 5 + [0.0]
    forward = compute_forward_returns(returns_series, horizon=1)

    result = compute_rsi_probability(
        rsi_series, returns_series, reference_rsi=50.0, bucket_width=10.0, min_sample_size=5
    )

    assert result is not None
    # forward returns for indices 0..9 (all rsi==50): shifted by 1 -> matches returns[1:10]+[None]
    valid_forward = [f for f in forward[:10] if f is not None]
    positive = sum(1 for f in valid_forward if f > 0)
    negative = sum(1 for f in valid_forward if f < 0)
    assert result["sample_size"] == len(valid_forward)
    assert result["prob_up_pct"] == round(100 * positive / len(valid_forward))
    assert result["prob_down_pct"] == round(100 * negative / len(valid_forward))


def test_compute_rsi_probability_ignores_out_of_bucket_points():
    rsi_series = [50.0] * 8 + [10.0] * 8
    returns_series = [0.02] * 8 + [-0.05] * 8
    forward = compute_forward_returns(returns_series, horizon=1)

    result = compute_rsi_probability(
        rsi_series, returns_series, reference_rsi=50.0, bucket_width=5.0, min_sample_size=5
    )

    assert result is not None
    matched_forward = [
        fwd
        for rsi, fwd in zip(rsi_series, forward)
        if rsi is not None and fwd is not None and 47.5 <= rsi <= 52.5
    ]
    positive = sum(1 for f in matched_forward if f > 0)
    assert result["sample_size"] == len(matched_forward)
    assert result["prob_up_pct"] == round(100 * positive / len(matched_forward))
    # The rsi==10 block (all negative forward returns) must be excluded from the bucket.
    assert result["prob_up_pct"] >= 80


def test_compute_forward_return_quantiles_empty_returns_none():
    assert compute_forward_return_quantiles([]) is None


def test_compute_forward_return_quantiles_median_of_odd_sample():
    # fractions, matching compute_rsi_probability's own "matches" convention
    matches = [-0.02, -0.01, 0.0, 0.01, 0.02]
    result = compute_forward_return_quantiles(matches)
    assert result["p50_pct"] == pytest.approx(0.0)
    assert result["p10_pct"] < result["p25_pct"] < result["p50_pct"]
    assert result["p50_pct"] < result["p75_pct"] < result["p90_pct"]


def test_compute_forward_return_quantiles_single_value_is_flat():
    result = compute_forward_return_quantiles([0.05])
    assert result == {
        "p10_pct": 5.0,
        "p25_pct": 5.0,
        "p50_pct": 5.0,
        "p75_pct": 5.0,
        "p90_pct": 5.0,
    }


def test_compute_rsi_probability_includes_quantiles_and_defaults_unconditioned():
    rsi_series = [50.0] * 10 + [90.0]
    returns_series = [0.01, -0.01] * 5 + [0.0]

    result = compute_rsi_probability(
        rsi_series, returns_series, reference_rsi=50.0, bucket_width=10.0, min_sample_size=5
    )

    assert result["regime_conditioned"] is False
    assert result["reference_regime"] is None
    assert result["p50_pct"] is not None
    assert result["p10_pct"] <= result["p50_pct"] <= result["p90_pct"]


def test_compute_rsi_probability_regime_conditioning_narrows_the_sample():
    # 10 RSI-matching points: 6 tagged "bull" (all positive forward returns),
    # 4 tagged "bear" (all negative) -- regime-conditioning on "bull" should
    # isolate the 6 positive-only matches instead of the mixed 10. Forward
    # returns are shifted one index ahead of the regime tag (index i's
    # forward return is returns_series[i+1]), so returns_series[1:7] (not
    # [0:6]) are the ones that land in the "bull"-tagged forward window.
    rsi_series = [50.0] * 10 + [90.0]
    returns_series = [0.0] + [0.02] * 6 + [-0.02] * 4
    regime_series = ["bull"] * 6 + ["bear"] * 4 + [None]

    result = compute_rsi_probability(
        rsi_series,
        returns_series,
        reference_rsi=50.0,
        bucket_width=10.0,
        min_sample_size=5,
        regime_series=regime_series,
        reference_regime="bull",
    )

    assert result is not None
    assert result["regime_conditioned"] is True
    assert result["reference_regime"] == "bull"
    assert result["sample_size"] == 6
    assert result["prob_up_pct"] == 100


def test_compute_rsi_probability_falls_back_when_regime_sample_too_small():
    # Only 2 "bull"-tagged matches (below min_sample_size=5) -- must fall
    # back to the full 10-point RSI-only sample rather than returning None.
    rsi_series = [50.0] * 10 + [90.0]
    returns_series = [0.01, -0.01] * 5 + [0.0]
    regime_series = ["bull"] * 2 + ["bear"] * 8 + [None]

    result = compute_rsi_probability(
        rsi_series,
        returns_series,
        reference_rsi=50.0,
        bucket_width=10.0,
        min_sample_size=5,
        regime_series=regime_series,
        reference_regime="bull",
    )

    assert result is not None
    assert result["regime_conditioned"] is False
    assert result["reference_regime"] is None
    assert result["sample_size"] == 10


# ---- Volatility conditioning (accuracy increment: reuses the same
# z-score approach app.services.knowledge.analysis.find_similar_episodes
# already validated, as one more opportunistic narrowing layer) ----


def test_compute_rsi_probability_volatility_conditioning_narrows_the_sample():
    # 10 RSI-matching points: 6 with volatility close to today's (20-ish),
    # 4 with wildly different volatility (200). Narrowing to the
    # similarly-volatile 6 should isolate their (all-positive) returns.
    rsi_series = [50.0] * 10 + [90.0]
    returns_series = [0.0] + [0.02] * 6 + [-0.02] * 4
    volatility_series = [20.0, 21.0, 19.0, 22.0, 18.0, 20.5] + [200.0] * 4 + [20.0]

    result = compute_rsi_probability(
        rsi_series,
        returns_series,
        reference_rsi=50.0,
        bucket_width=10.0,
        min_sample_size=5,
        volatility_series=volatility_series,
        reference_volatility=20.0,
    )

    assert result is not None
    assert result["volatility_conditioned"] is True
    assert result["reference_volatility"] == pytest.approx(20.0)
    assert result["sample_size"] == 6
    assert result["prob_up_pct"] == 100


def test_compute_rsi_probability_falls_back_when_volatility_sample_too_small():
    # Only 2 points share today's volatility band -- below min_sample_size=5
    # -- must fall back to the full 10-point RSI-only sample.
    rsi_series = [50.0] * 10 + [90.0]
    returns_series = [0.01, -0.01] * 5 + [0.0]
    volatility_series = [20.0, 21.0] + [200.0] * 8 + [20.0]

    result = compute_rsi_probability(
        rsi_series,
        returns_series,
        reference_rsi=50.0,
        bucket_width=10.0,
        min_sample_size=5,
        volatility_series=volatility_series,
        reference_volatility=20.0,
    )

    assert result is not None
    assert result["volatility_conditioned"] is False
    assert result["reference_volatility"] is None
    assert result["sample_size"] == 10


def test_compute_rsi_probability_regime_and_volatility_conditioning_stack():
    # 6 "bull"-tagged matches; within those, 4 share today's volatility band
    # and 2 don't. Both conditions should apply in sequence: regime narrows
    # 10 -> 6, then volatility narrows 6 -> 4.
    rsi_series = [50.0] * 10 + [90.0]
    returns_series = [0.0] + [0.02] * 6 + [-0.02] * 4
    regime_series = ["bull"] * 6 + ["bear"] * 4 + [None]
    volatility_series = [20.0, 21.0, 19.0, 22.0, 200.0, 200.0] + [30.0] * 4 + [20.0]

    result = compute_rsi_probability(
        rsi_series,
        returns_series,
        reference_rsi=50.0,
        bucket_width=10.0,
        min_sample_size=4,
        regime_series=regime_series,
        reference_regime="bull",
        volatility_series=volatility_series,
        reference_volatility=20.0,
    )

    assert result is not None
    assert result["regime_conditioned"] is True
    assert result["volatility_conditioned"] is True
    assert result["sample_size"] == 4


def test_compute_rsi_probability_volatility_series_ignored_when_none():
    # No volatility_series/reference_volatility given -> identical to the
    # existing RSI-only behavior, never activated implicitly.
    rsi_series = [50.0] * 10 + [90.0]
    returns_series = [0.01, -0.01] * 5 + [0.0]

    result = compute_rsi_probability(
        rsi_series, returns_series, reference_rsi=50.0, bucket_width=10.0, min_sample_size=5
    )

    assert result["volatility_conditioned"] is False
    assert result["reference_volatility"] is None


# ---- POST-V9 Phase 4: compute_quantile_coverage ----


def test_compute_quantile_coverage_perfect_p10_p90_hit_rate():
    evaluated = [_graded(3.0), _graded(-4.0), _graded(0.0), _graded(4.9)]  # all inside [-5, 5]

    coverage = compute_quantile_coverage(evaluated)

    assert coverage["p10_p90"]["expected_coverage_pct"] == 80.0
    assert coverage["p10_p90"]["realized_coverage_pct"] == 100.0
    assert coverage["p10_p90"]["sample_count"] == 4
    assert coverage["p10_p90"]["coverage_gap_pct"] == 20.0


def test_compute_quantile_coverage_counts_misses_outside_the_band():
    evaluated = [_graded(3.0), _graded(10.0), _graded(-10.0), _graded(0.0)]  # 2 of 4 outside

    coverage = compute_quantile_coverage(evaluated)

    assert coverage["p10_p90"]["realized_coverage_pct"] == 50.0
    assert coverage["p10_p90"]["coverage_gap_pct"] == -30.0


def test_compute_quantile_coverage_excludes_rows_missing_bounds_never_counts_as_miss():
    evaluated = [
        _graded(3.0),
        {
            "realized_return_pct": 100.0,
            "p10_pct": None,
            "p90_pct": None,
            "p25_pct": None,
            "p75_pct": None,
        },
    ]

    coverage = compute_quantile_coverage(evaluated)

    assert coverage["p10_p90"]["sample_count"] == 1
    assert coverage["p10_p90"]["realized_coverage_pct"] == 100.0


def test_compute_quantile_coverage_empty_is_none_not_zero():
    coverage = compute_quantile_coverage([])
    assert coverage["p10_p90"]["realized_coverage_pct"] is None
    assert coverage["p10_p90"]["sample_count"] == 0
    assert coverage["p10_p90"]["sample_sufficiency"] == "insufficient"


def test_compute_quantile_coverage_reports_sample_sufficiency():
    evaluated = [_graded(1.0) for _ in range(3)]

    coverage = compute_quantile_coverage(evaluated, min_sample_size=5, reliable_sample_size=10)

    assert coverage["p10_p90"]["sample_sufficiency"] == "insufficient"


def test_compute_quantile_coverage_both_intervals_scored_independently():
    # inside p25-p75 (-2..2) but also inside p10-p90 -- both should show it
    evaluated = [_graded(1.0), _graded(1.0), _graded(1.0)]

    coverage = compute_quantile_coverage(evaluated)

    assert coverage["p25_p75"]["realized_coverage_pct"] == 100.0
    assert coverage["p10_p90"]["realized_coverage_pct"] == 100.0
    assert coverage["p25_p75"]["expected_coverage_pct"] == 50.0


# ---- POST-V9 Phase 4: compute_quantile_coverage_by_group ----


def test_compute_quantile_coverage_by_group_partitions_by_regime():
    evaluated = [
        _graded(3.0, reference_regime="bull"),
        _graded(10.0, reference_regime="bull"),  # miss in bull
        _graded(1.0, reference_regime="bear"),
        _graded(-1.0, reference_regime="bear"),
    ]

    by_regime = compute_quantile_coverage_by_group(evaluated, "reference_regime")

    assert by_regime["bull"]["p10_p90"]["realized_coverage_pct"] == 50.0
    assert by_regime["bear"]["p10_p90"]["realized_coverage_pct"] == 100.0


def test_compute_quantile_coverage_by_group_groups_missing_key_under_none():
    evaluated = [_graded(1.0), _graded(2.0)]  # no reference_regime key at all

    by_regime = compute_quantile_coverage_by_group(evaluated, "reference_regime")

    assert None in by_regime
    assert by_regime[None]["p10_p90"]["sample_count"] == 2


def test_compute_quantile_coverage_by_group_partitions_by_horizon():
    evaluated = [
        _graded(3.0, horizon_periods=1),
        _graded(10.0, horizon_periods=7),  # miss at 7-period horizon
    ]

    by_horizon = compute_quantile_coverage_by_group(evaluated, "horizon_periods")

    assert by_horizon[1]["p10_p90"]["realized_coverage_pct"] == 100.0
    assert by_horizon[7]["p10_p90"]["realized_coverage_pct"] == 0.0
