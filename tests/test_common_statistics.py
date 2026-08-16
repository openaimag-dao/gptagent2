from app.services.common.statistics import compute_bootstrap_ci, compute_wilson_interval


def test_compute_wilson_interval_none_for_zero_total():
    assert compute_wilson_interval(0, 0) is None


def test_compute_wilson_interval_point_estimate_matches_raw_proportion():
    result = compute_wilson_interval(52, 100)
    assert result["point_estimate_pct"] == 52.0
    assert result["sample_count"] == 100


def test_compute_wilson_interval_bounds_never_exceed_0_100():
    result = compute_wilson_interval(1, 2)
    assert 0.0 <= result["lower_pct"] <= result["upper_pct"] <= 100.0


def test_compute_wilson_interval_widens_at_small_sample_size():
    small = compute_wilson_interval(5, 10)
    large = compute_wilson_interval(500, 1000)
    # same 50% point estimate, but the small-sample interval must be wider
    assert small["point_estimate_pct"] == large["point_estimate_pct"] == 50.0
    assert (small["upper_pct"] - small["lower_pct"]) > (large["upper_pct"] - large["lower_pct"])


def test_compute_wilson_interval_never_claims_precision_52_vs_51_at_low_n():
    # the exact motivating example from the spec: 52% vs 51% must not read
    # as a settled improvement when N is tiny -- their intervals should
    # overlap heavily.
    a = compute_wilson_interval(52, 100)
    b = compute_wilson_interval(51, 100)
    assert a["lower_pct"] < b["upper_pct"]  # intervals overlap


def test_compute_wilson_interval_100_pct_all_successes():
    result = compute_wilson_interval(10, 10)
    assert result["point_estimate_pct"] == 100.0
    assert result["upper_pct"] == 100.0
    assert result["lower_pct"] < 100.0  # still honest about uncertainty


def test_compute_bootstrap_ci_none_below_two_samples():
    assert compute_bootstrap_ci([]) is None
    assert compute_bootstrap_ci([0.05]) is None


def test_compute_bootstrap_ci_point_estimate_matches_mean():
    values = [0.01, 0.02, 0.03, -0.01]
    result = compute_bootstrap_ci(values, seed=42)
    assert result["point_estimate"] == round(sum(values) / len(values), 4)
    assert result["sample_count"] == 4


def test_compute_bootstrap_ci_bounds_bracket_the_point_estimate():
    values = [0.01, 0.05, -0.02, 0.03, 0.01, -0.01, 0.02]
    result = compute_bootstrap_ci(values, seed=1)
    assert result["lower"] <= result["point_estimate"] <= result["upper"]


def test_compute_bootstrap_ci_deterministic_with_fixed_seed():
    values = [0.01, 0.02, -0.03, 0.04, 0.0]
    first = compute_bootstrap_ci(values, seed=7)
    second = compute_bootstrap_ci(values, seed=7)
    assert first == second


def test_compute_bootstrap_ci_narrows_with_larger_consistent_sample():
    # a large sample of near-identical values should bootstrap to a
    # tighter interval than a small, more variable one.
    consistent = [0.02] * 200
    variable = [0.02, -0.05, 0.08, -0.03, 0.01]
    tight = compute_bootstrap_ci(consistent, seed=3)
    wide = compute_bootstrap_ci(variable, seed=3)
    assert (tight["upper"] - tight["lower"]) < (wide["upper"] - wide["lower"])
