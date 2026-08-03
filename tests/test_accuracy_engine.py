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


def test_aggregate_stats_honest_none_when_nothing_graded():
    rows = [_row(error_pct=None, direction_correct=None, confidence_correct=None)]
    stats = _aggregate_stats(rows)
    assert stats["evaluated_count"] == 1
    assert stats["avg_abs_error_pct"] is None
    assert stats["direction_accuracy_pct"] is None
    assert stats["confidence_accuracy_pct"] is None


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
        _row(symbol="BTC", evaluated_at=datetime(2026, 8, 1, tzinfo=UTC)),
        _row(symbol="BTC", evaluated_at=datetime(2026, 8, 2, tzinfo=UTC)),
    ]
    engine = AccuracyEngine(_session_factory(rows))

    result = await engine.compute()

    assert result["overall"]["evaluated_count"] == 2
    assert len(result["daily"]) == 2
    assert len(result["by_asset"]) == 1
    assert len(result["recent"]) == 2
    assert result["recent"][0]["symbol"] == "BTC"


async def test_compute_with_no_graded_rows():
    engine = AccuracyEngine(_session_factory([]))
    result = await engine.compute()
    assert result["overall"]["evaluated_count"] == 0
    assert result["daily"] == []
    assert result["by_asset"] == []
    assert result["recent"] == []
