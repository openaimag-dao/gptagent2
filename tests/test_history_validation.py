from datetime import UTC, datetime, timedelta

from app.services.history.schemas import Timeframe
from app.services.history.validation import find_duplicate_timestamps, find_gaps, validate_series


def _daily(*days: int) -> list[datetime]:
    base = datetime(2026, 1, 1, tzinfo=UTC)
    return [base + timedelta(days=d) for d in days]


def test_find_duplicate_timestamps_none():
    timestamps = _daily(0, 1, 2)
    assert find_duplicate_timestamps(timestamps) == []


def test_find_duplicate_timestamps_detects_repeats():
    timestamps = _daily(0, 1, 1, 2, 2, 2)
    duplicates = find_duplicate_timestamps(timestamps)
    assert len(duplicates) == 3


def test_find_gaps_none_for_contiguous_daily_series():
    timestamps = _daily(0, 1, 2, 3, 4)
    assert find_gaps(timestamps, Timeframe.DAILY, market="crypto") == []


def test_find_gaps_detects_a_real_gap_in_crypto_series():
    # crypto trades 24/7, so a 5-day hole is a real gap even with generous tolerance
    timestamps = _daily(0, 1, 7, 8)
    gaps = find_gaps(timestamps, Timeframe.DAILY, market="crypto")
    assert len(gaps) == 1
    assert gaps[0].after == _daily(1)[0]
    assert gaps[0].before == _daily(7)[0]


def test_find_gaps_tolerates_weekends_for_equities():
    # Fri -> Mon is a normal 3-day equity gap, not a data problem
    friday = datetime(2026, 1, 2, tzinfo=UTC)  # a Friday
    monday = friday + timedelta(days=3)
    assert find_gaps([friday, monday], Timeframe.DAILY, market="equity") == []


def test_find_gaps_still_flags_a_large_equity_gap():
    start = datetime(2026, 1, 2, tzinfo=UTC)
    two_weeks_later = start + timedelta(days=14)
    gaps = find_gaps([start, two_weeks_later], Timeframe.DAILY, market="equity")
    assert len(gaps) == 1


def test_validate_series_combines_duplicates_and_gaps():
    timestamps = _daily(0, 1, 1, 8)
    report = validate_series("BTC", Timeframe.DAILY, timestamps, market="crypto")
    assert report.symbol == "BTC"
    assert len(report.duplicate_timestamps) == 1
    assert len(report.gaps) == 1
