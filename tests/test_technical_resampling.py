from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.services.technical.resampling import resample_to_weekly


def _daily(day_offset: int, open_, high, low, close, volume=10.0):
    return SimpleNamespace(
        timestamp=datetime(2026, 1, 5, tzinfo=UTC) + timedelta(days=day_offset),  # a Monday
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def test_resample_to_weekly_groups_by_iso_week():
    rows = [
        _daily(0, 100.0, 105.0, 95.0, 102.0),  # Mon
        _daily(1, 102.0, 110.0, 101.0, 108.0),  # Tue
        _daily(2, 108.0, 109.0, 90.0, 95.0),  # Wed -- same week
        _daily(7, 95.0, 96.0, 93.0, 94.0),  # next Monday -- new week
    ]
    weekly = resample_to_weekly(rows)
    assert len(weekly) == 2
    first_week = weekly[0]
    assert first_week.open == 100.0  # Monday's open
    assert first_week.high == 110.0  # Tuesday's high
    assert first_week.low == 90.0  # Wednesday's low
    assert first_week.close == 95.0  # Wednesday's close (last day of that week)
    assert first_week.volume == 30.0


def test_resample_to_weekly_handles_missing_volume():
    rows = [_daily(0, 100.0, 105.0, 95.0, 102.0, volume=None)]
    weekly = resample_to_weekly(rows)
    assert weekly[0].volume is None


def test_resample_to_weekly_empty_input():
    assert resample_to_weekly([]) == []
