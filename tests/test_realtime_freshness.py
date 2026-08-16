from datetime import UTC, datetime, timedelta

from app.services.realtime.freshness import age_seconds, classify_freshness


def _classify(age):
    return classify_freshness(
        age, live_seconds=5.0, recent_seconds=30.0, delayed_seconds=120.0, stale_seconds=300.0
    )


def test_classify_freshness_live_below_live_threshold():
    assert _classify(0.0) == "live"
    assert _classify(4.9) == "live"


def test_classify_freshness_recent_at_and_above_live_threshold():
    assert _classify(5.0) == "recent"
    assert _classify(29.9) == "recent"


def test_classify_freshness_delayed_at_and_above_recent_threshold():
    assert _classify(30.0) == "delayed"
    assert _classify(119.9) == "delayed"


def test_classify_freshness_stale_at_and_above_delayed_threshold():
    assert _classify(120.0) == "stale"
    assert _classify(299.9) == "stale"


def test_classify_freshness_offline_at_and_above_stale_threshold():
    assert _classify(300.0) == "offline"
    assert _classify(10_000.0) == "offline"


def test_classify_freshness_clamps_negative_age_to_zero():
    # A slightly-in-the-future timestamp (clock skew) is still "live", not
    # a crash or a nonsensical negative age.
    assert _classify(-1.0) == "live"


def test_classify_freshness_uses_the_thresholds_passed_in_not_hardcoded_values():
    # Same raw age, different threshold sets -- proves the bands are
    # config-driven, not hardcoded inside classify_freshness itself.
    assert (
        classify_freshness(
            10.0, live_seconds=1.0, recent_seconds=2.0, delayed_seconds=3.0, stale_seconds=4.0
        )
        == "offline"
    )
    assert (
        classify_freshness(
            10.0,
            live_seconds=100.0,
            recent_seconds=200.0,
            delayed_seconds=300.0,
            stale_seconds=400.0,
        )
        == "live"
    )


def test_age_seconds_computes_the_gap_between_reference_and_now():
    now = datetime(2026, 1, 1, 12, 0, 30, tzinfo=UTC)
    reference = now - timedelta(seconds=12)
    assert age_seconds(reference, now=now) == 12.0
