from datetime import UTC, datetime, timedelta

from app.services.alerts.engine import _is_on_cooldown


def test_is_on_cooldown_none_when_never_broadcast():
    assert _is_on_cooldown(None, datetime.now(UTC)) is False


def test_is_on_cooldown_true_within_window():
    now = datetime.now(UTC)
    last = now - timedelta(minutes=10)
    assert _is_on_cooldown(last, now, cooldown_minutes=60) is True


def test_is_on_cooldown_false_after_window_elapses():
    now = datetime.now(UTC)
    last = now - timedelta(minutes=90)
    assert _is_on_cooldown(last, now, cooldown_minutes=60) is False
