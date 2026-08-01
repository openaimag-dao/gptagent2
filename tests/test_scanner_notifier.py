from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.scanner.notifier import send_scanner_notifications


def _session_factory(existing_alert=None):
    session = AsyncMock()
    session.scalar = AsyncMock(return_value=existing_alert)
    session.get = AsyncMock(return_value=existing_alert)
    session.commit = AsyncMock()
    session.__aenter__.return_value = session
    return MagicMock(return_value=session), session


def _detection(
    action="new", notify_eligible=True, tier="high", alert_key="scanner:price_event:BTC:up"
):
    return {
        "alert_key": alert_key,
        "alert_log_id": 42,
        "category": "price_event",
        "symbols": ["BTC"],
        "tier": tier,
        "quality_score": 70.0,
        "action": action,
        "notify_eligible": notify_eligible,
        "message": "BTC +9.00% (24h)",
        "title": "BTC SURGE",
        "direction": "up",
        "readings": [{"symbol": "BTC", "price": 65000.0, "change_pct_24h": 9.0, "volume_24h": 1.0}],
        "context": {"regime": "risk_on", "risk_score": 30, "confidence_score": 70},
    }


async def test_skips_non_notify_eligible_detections():
    session_factory, session = _session_factory()
    with patch("app.services.scanner.notifier.send_text_to_with_id", AsyncMock()) as send_mock:
        sent = await send_scanner_notifications(
            session_factory, [_detection(notify_eligible=False)]
        )

    assert sent == 0
    send_mock.assert_not_awaited()
    session.commit.assert_not_awaited()


async def test_new_action_broadcasts_and_marks_alert_log():
    # session.scalar (the ScannerAlert lookup) returns None -- no existing
    # active episode -- so only the AlertLog row is ever session.get()'d.
    session_factory, session = _session_factory(existing_alert=None)
    settings = SimpleNamespace(telegram_broadcast_chat_ids="111,222")
    log_row = SimpleNamespace(id=42, broadcast=False)
    session.get = AsyncMock(return_value=log_row)

    with (
        patch("app.services.scanner.notifier.get_settings", return_value=settings),
        patch(
            "app.services.scanner.notifier.send_text_to_with_id",
            AsyncMock(side_effect=[101, 102]),
        ) as send_mock,
    ):
        sent = await send_scanner_notifications(session_factory, [_detection(action="new")])

    assert sent == 1
    assert send_mock.await_count == 2  # one per chat id
    assert log_row.broadcast is True


async def test_escalate_edits_existing_message_when_ids_present():
    existing_alert = SimpleNamespace(
        id=1, telegram_message_ids={"111": 555}, active=True, last_updated_at=None
    )
    session_factory, session = _session_factory(existing_alert)
    log_row = SimpleNamespace(id=42, broadcast=False)
    session.get = AsyncMock(side_effect=[existing_alert, log_row])

    with patch(
        "app.services.scanner.notifier.edit_text", AsyncMock(return_value=True)
    ) as edit_mock:
        sent = await send_scanner_notifications(session_factory, [_detection(action="escalate")])

    assert sent == 1
    edit_mock.assert_awaited_once()
    chat_id, message_id, _text = edit_mock.call_args.args
    assert (chat_id, message_id) == (111, 555)


async def test_escalate_without_existing_message_ids_broadcasts_new():
    existing_alert = SimpleNamespace(
        id=1, telegram_message_ids={}, active=True, last_updated_at=None
    )
    session_factory, session = _session_factory(existing_alert)
    settings = SimpleNamespace(telegram_broadcast_chat_ids="111")
    log_row = SimpleNamespace(id=42, broadcast=False)
    session.get = AsyncMock(side_effect=[existing_alert, log_row])

    with (
        patch("app.services.scanner.notifier.get_settings", return_value=settings),
        patch(
            "app.services.scanner.notifier.send_text_to_with_id", AsyncMock(return_value=999)
        ) as send_mock,
    ):
        sent = await send_scanner_notifications(session_factory, [_detection(action="escalate")])

    assert sent == 1
    send_mock.assert_awaited_once()


async def test_failed_send_does_not_mark_anything_notified():
    session_factory, session = _session_factory()
    settings = SimpleNamespace(telegram_broadcast_chat_ids="111")

    with (
        patch("app.services.scanner.notifier.get_settings", return_value=settings),
        patch("app.services.scanner.notifier.send_text_to_with_id", AsyncMock(return_value=None)),
    ):
        sent = await send_scanner_notifications(session_factory, [_detection(action="new")])

    assert sent == 0
    session.commit.assert_not_awaited()
