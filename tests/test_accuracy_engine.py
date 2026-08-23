from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.accuracy.engine import (
    AccuracyEngine,
    _aggregate_stats,
    _period_key,
    bucket_accuracy,
    overall_summary,
    summarize_by_asset,
    summarize_by_regime_horizon,
)


def _row(
    symbol="BTC",
    error_pct=1.0,
    direction_correct=True,
    confidence_correct=True,
    evaluated_at=datetime(2026, 8, 1, tzinfo=UTC),
    horizon="24h",
    computed_at=datetime(2026, 7, 31, tzinfo=UTC),
    target_price=100.0,
    realized_price=101.0,
    confidence_tier="Strong",
    momentum_baseline_correct=None,
    historical_mean_baseline_error_pct=None,
    zero_return_baseline_error_pct=None,
    regime_mean_baseline_error_pct=None,
    regime_at_forecast=None,
    target_reached=None,
):
    return SimpleNamespace(
        symbol=symbol,
        error_pct=error_pct,
        direction_correct=direction_correct,
        confidence_correct=confidence_correct,
        evaluated_at=evaluated_at,
        horizon=horizon,
        computed_at=computed_at,
        target_price=target_price,
        realized_price=realized_price,
        confidence_tier=confidence_tier,
        momentum_baseline_correct=momentum_baseline_correct,
        historical_mean_baseline_error_pct=historical_mean_baseline_error_pct,
        zero_return_baseline_error_pct=zero_return_baseline_error_pct,
        regime_mean_baseline_error_pct=regime_mean_baseline_error_pct,
        regime_at_forecast=regime_at_forecast,
        target_reached=target_reached,
    )


# -- pure functions -----------------------------------------------------------


def test_period_key_daily_weekly_monthly():
    d = datetime(2026, 8, 3, tzinfo=UTC).date()
    assert _period_key(d, "daily") == "2026-08-03"
    assert _period_key(d, "monthly") == "2026-08"
    assert _period_key(d, "weekly").startswith("2026-W")


def test_aggregate_stats_real_averages():
    rows = [
        _row(error_pct=1.0, direction_correct=True, confidence_correct=True),
        _row(error_pct=3.0, direction_correct=False, confidence_correct=False),
    ]
    stats = _aggregate_stats(rows)
    assert stats["evaluated_count"] == 2
    assert stats["avg_abs_error_pct"] == 2.0
    assert stats["direction_accuracy_pct"] == 50.0
    assert stats["confidence_accuracy_pct"] == 50.0
    # POST-V9 Phase 14: no baseline data on these fixture rows -> honestly
    # absent, not fabricated
    assert stats["beats_random_walk"] is False  # 50% is not > 50%
    assert stats["momentum_baseline_accuracy_pct"] is None
    assert stats["beats_momentum_baseline"] is None
    assert stats["historical_mean_baseline_avg_abs_error_pct"] is None
    assert stats["beats_historical_mean_baseline"] is None
    assert stats["zero_return_baseline_avg_abs_error_pct"] is None
    assert stats["beats_zero_return_baseline"] is None
    assert stats["regime_mean_baseline_avg_abs_error_pct"] is None
    assert stats["beats_regime_mean_baseline"] is None


def test_aggregate_stats_honest_none_when_nothing_graded():
    rows = [_row(error_pct=None, direction_correct=None, confidence_correct=None)]
    stats = _aggregate_stats(rows)
    assert stats["evaluated_count"] == 1
    assert stats["avg_abs_error_pct"] is None
    assert stats["direction_accuracy_pct"] is None
    assert stats["confidence_accuracy_pct"] is None
    assert stats["beats_random_walk"] is None


# ---- POST-V9 Phase 14: baseline comparison ----


def test_aggregate_stats_beats_random_walk_when_above_50_pct():
    rows = [_row(direction_correct=True)] * 6 + [_row(direction_correct=False)] * 4
    stats = _aggregate_stats(rows)
    assert stats["direction_accuracy_pct"] == 60.0
    assert stats["beats_random_walk"] is True


def test_aggregate_stats_momentum_baseline_comparison():
    rows = [
        _row(direction_correct=True, momentum_baseline_correct=False),
        _row(direction_correct=True, momentum_baseline_correct=False),
        _row(direction_correct=False, momentum_baseline_correct=True),
    ]
    stats = _aggregate_stats(rows)
    assert stats["direction_accuracy_pct"] == round(100 * 2 / 3, 2)
    assert stats["momentum_baseline_accuracy_pct"] == round(100 * 1 / 3, 2)
    assert stats["beats_momentum_baseline"] is True


def test_aggregate_stats_does_not_beat_momentum_baseline_when_worse():
    rows = [
        _row(direction_correct=False, momentum_baseline_correct=True),
        _row(direction_correct=False, momentum_baseline_correct=True),
        _row(direction_correct=True, momentum_baseline_correct=False),
    ]
    stats = _aggregate_stats(rows)
    assert stats["beats_momentum_baseline"] is False


def test_aggregate_stats_historical_mean_baseline_comparison():
    rows = [
        _row(error_pct=1.0, historical_mean_baseline_error_pct=5.0),
        _row(error_pct=-1.0, historical_mean_baseline_error_pct=-5.0),
    ]
    stats = _aggregate_stats(rows)
    assert stats["avg_abs_error_pct"] == 1.0
    assert stats["historical_mean_baseline_avg_abs_error_pct"] == 5.0
    # smaller absolute error is better -- the forecast's own 1.0% beats the
    # naive baseline's 5.0%
    assert stats["beats_historical_mean_baseline"] is True


def test_aggregate_stats_zero_return_baseline_comparison():
    rows = [
        _row(error_pct=1.0, zero_return_baseline_error_pct=8.0),
        _row(error_pct=-1.0, zero_return_baseline_error_pct=-8.0),
    ]
    stats = _aggregate_stats(rows)
    assert stats["avg_abs_error_pct"] == 1.0
    assert stats["zero_return_baseline_avg_abs_error_pct"] == 8.0
    # smaller absolute error is better -- the forecast's own 1.0% beats the
    # naive "assume no change" baseline's 8.0%
    assert stats["beats_zero_return_baseline"] is True


def test_aggregate_stats_does_not_beat_zero_return_baseline_when_worse():
    rows = [
        _row(error_pct=9.0, zero_return_baseline_error_pct=2.0),
        _row(error_pct=-9.0, zero_return_baseline_error_pct=-2.0),
    ]
    stats = _aggregate_stats(rows)
    assert stats["beats_zero_return_baseline"] is False


def test_aggregate_stats_regime_mean_baseline_comparison():
    rows = [
        _row(error_pct=1.0, regime_mean_baseline_error_pct=6.0),
        _row(error_pct=-1.0, regime_mean_baseline_error_pct=-6.0),
    ]
    stats = _aggregate_stats(rows)
    assert stats["avg_abs_error_pct"] == 1.0
    assert stats["regime_mean_baseline_avg_abs_error_pct"] == 6.0
    # smaller absolute error is better -- the forecast's own 1.0% beats the
    # naive "same regime, historical average" baseline's 6.0%
    assert stats["beats_regime_mean_baseline"] is True


def test_aggregate_stats_does_not_beat_regime_mean_baseline_when_worse():
    rows = [
        _row(error_pct=9.0, regime_mean_baseline_error_pct=2.0),
        _row(error_pct=-9.0, regime_mean_baseline_error_pct=-2.0),
    ]
    stats = _aggregate_stats(rows)
    assert stats["beats_regime_mean_baseline"] is False


# ---- Forecast Intelligence Upgrade: target_reached (intrabar touch) --------


def test_aggregate_stats_target_hit_rate_honestly_none_without_data():
    stats = _aggregate_stats([_row(target_reached=None)])
    assert stats["target_hit_rate_pct"] is None


def test_aggregate_stats_target_hit_rate_pct():
    rows = [
        _row(target_reached=True),
        _row(target_reached=True),
        _row(target_reached=False),
    ]
    stats = _aggregate_stats(rows)
    assert stats["target_hit_rate_pct"] == round(100 * 2 / 3, 2)


# ---- POST-V9 Phase 16: regime x horizon interaction matrix ----


def test_summarize_by_regime_horizon_groups_by_combined_key():
    rows = [
        _row(regime_at_forecast="ACCUMULATION", horizon="24h", direction_correct=True),
        _row(regime_at_forecast="ACCUMULATION", horizon="24h", direction_correct=False),
        _row(regime_at_forecast="ACCUMULATION", horizon="7d", direction_correct=True),
        _row(regime_at_forecast="CAPITULATION", horizon="24h", direction_correct=True),
    ]
    matrix = summarize_by_regime_horizon(rows)
    cells = [(c["regime"], c["horizon"]) for c in matrix]
    assert cells == [
        ("ACCUMULATION", "24h"),
        ("ACCUMULATION", "7d"),
        ("CAPITULATION", "24h"),
    ]
    acc_24h = next(c for c in matrix if c["regime"] == "ACCUMULATION" and c["horizon"] == "24h")
    assert acc_24h["evaluated_count"] == 2
    assert acc_24h["direction_accuracy_pct"] == 50.0


def test_summarize_by_regime_horizon_excludes_rows_without_regime():
    rows = [
        _row(regime_at_forecast=None, horizon="24h"),
        _row(regime_at_forecast="ACCUMULATION", horizon="24h"),
    ]
    matrix = summarize_by_regime_horizon(rows)
    assert len(matrix) == 1
    assert matrix[0]["evaluated_count"] == 1


def test_summarize_by_regime_horizon_excludes_ungraded_rows():
    rows = [_row(regime_at_forecast="ACCUMULATION", horizon="24h", evaluated_at=None)]
    assert summarize_by_regime_horizon(rows) == []


def test_bucket_accuracy_groups_by_day():
    rows = [
        _row(evaluated_at=datetime(2026, 8, 1, 10, tzinfo=UTC), error_pct=1.0),
        _row(evaluated_at=datetime(2026, 8, 1, 20, tzinfo=UTC), error_pct=3.0),
        _row(evaluated_at=datetime(2026, 8, 2, tzinfo=UTC), error_pct=2.0),
    ]
    buckets = bucket_accuracy(rows, "daily")
    assert [b["period"] for b in buckets] == ["2026-08-01", "2026-08-02"]
    assert buckets[0]["evaluated_count"] == 2
    assert buckets[0]["avg_abs_error_pct"] == 2.0
    assert buckets[1]["evaluated_count"] == 1


def test_bucket_accuracy_skips_ungraded_rows():
    rows = [_row(evaluated_at=None)]
    assert bucket_accuracy(rows, "daily") == []


def test_summarize_by_asset_groups_per_symbol():
    rows = [
        _row(symbol="BTC", error_pct=1.0),
        _row(symbol="ETH", error_pct=2.0),
        _row(symbol="BTC", error_pct=3.0),
    ]
    by_asset = summarize_by_asset(rows)
    assert [a["symbol"] for a in by_asset] == ["BTC", "ETH"]
    assert by_asset[0]["evaluated_count"] == 2
    assert by_asset[0]["avg_abs_error_pct"] == 2.0


def test_overall_summary_ignores_ungraded():
    rows = [_row(evaluated_at=None), _row(error_pct=2.0)]
    assert overall_summary(rows)["evaluated_count"] == 1


# -- AccuracyEngine.compute ----------------------------------------------------


def _session_factory(rows):
    session = AsyncMock()
    session.scalars = AsyncMock(return_value=rows)
    session.__aenter__.return_value = session
    return MagicMock(return_value=session)


async def test_compute_returns_all_views():
    rows = [
        _row(
            symbol="BTC",
            evaluated_at=datetime(2026, 8, 1, tzinfo=UTC),
            regime_at_forecast="ACCUMULATION",
        ),
        _row(symbol="BTC", evaluated_at=datetime(2026, 8, 2, tzinfo=UTC)),
    ]
    engine = AccuracyEngine(_session_factory(rows))

    result = await engine.compute()

    assert result["overall"]["evaluated_count"] == 2
    assert len(result["daily"]) == 2
    assert len(result["by_asset"]) == 1
    assert len(result["recent"]) == 2
    assert result["recent"][0]["symbol"] == "BTC"
    # POST-V9 Phase 16: only the row with a recorded regime lands in the matrix
    assert len(result["by_regime_horizon"]) == 1
    assert result["by_regime_horizon"][0]["regime"] == "ACCUMULATION"


async def test_compute_with_no_graded_rows():
    engine = AccuracyEngine(_session_factory([]))
    result = await engine.compute()
    assert result["overall"]["evaluated_count"] == 0
    assert result["daily"] == []
    assert result["by_asset"] == []
    assert result["by_regime_horizon"] == []
    assert result["recent"] == []
