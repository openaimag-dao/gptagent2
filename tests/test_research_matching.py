from datetime import UTC, datetime

from app.services.research.matching import nearest_bar_index


def _dt(day: int) -> datetime:
    return datetime(2024, 1, day, tzinfo=UTC)


def test_none_when_no_timestamps():
    assert nearest_bar_index([], _dt(1)) is None


def test_finds_exact_match():
    timestamps = [_dt(1), _dt(2), _dt(3)]
    assert nearest_bar_index(timestamps, _dt(2)) == 1


def test_finds_closest_when_no_exact_match():
    timestamps = [_dt(1), _dt(5), _dt(10)]
    assert nearest_bar_index(timestamps, _dt(6)) == 1


def test_none_when_nothing_within_tolerance():
    timestamps = [_dt(1), _dt(2)]
    assert nearest_bar_index(timestamps, _dt(20), tolerance_days=3.0) is None


def test_respects_custom_tolerance():
    timestamps = [_dt(1)]
    assert nearest_bar_index(timestamps, _dt(3), tolerance_days=1.0) is None
    assert nearest_bar_index(timestamps, _dt(3), tolerance_days=5.0) == 0
