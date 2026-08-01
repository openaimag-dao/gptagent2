"""Thin Telegram adapter for the v5.5 Market Scanner. Deliberately kept OUT
of app/services/scanner/engine.py (MarketScannerEngine never imports
app.telegram.* -- "Never send Telegram messages directly" from the
mission): this module is the only place scanner detections actually reach
Telegram, called by the scheduler job after MarketScannerEngine.run_cycle()
returns its processed detections. Escalation reuses the exact same
new/escalate broadcast-or-edit pattern v5.1's CriticalAlertEngine
established (app.telegram.broadcast.send_text_to_with_id/edit_text) --
"Only HIGH and CRITICAL events should notify users" is already enforced
upstream by MarketScannerEngine's `notify_eligible` flag (gate_severity +
should_notify, reused from app.services.shocks.detectors), so this module
only has to act on it, not re-derive it.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import AlertLog, ScannerAlert
from app.telegram.broadcast import edit_text, parse_chat_ids, send_text_to_with_id
from app.telegram.formatters import format_scanner_alert

logger = logging.getLogger(__name__)


async def _broadcast_new(message: str) -> dict[str, int]:
    chat_ids = parse_chat_ids(get_settings().telegram_broadcast_chat_ids)
    ids: dict[str, int] = {}
    for chat_id in chat_ids:
        message_id = await send_text_to_with_id(chat_id, message)
        if message_id is not None:
            ids[str(chat_id)] = message_id
    return ids


async def _edit_existing(telegram_message_ids: dict, message: str) -> bool:
    any_ok = False
    for chat_id_str, message_id in telegram_message_ids.items():
        ok = await edit_text(int(chat_id_str), message_id, message)
        any_ok = any_ok or ok
    return any_ok


async def send_scanner_notifications(
    session_factory: async_sessionmaker[AsyncSession], processed: list[dict]
) -> int:
    """Sends Telegram for every notify-eligible detection
    MarketScannerEngine just processed, then marks the corresponding
    ScannerAlert/AlertLog rows as notified. Returns how many were actually
    sent."""
    sent = 0
    for detection in processed:
        if not detection.get("notify_eligible"):
            continue

        message = format_scanner_alert(detection)

        async with session_factory() as session:
            alert = await session.scalar(
                select(ScannerAlert)
                .where(
                    ScannerAlert.alert_key == detection["alert_key"], ScannerAlert.active.is_(True)
                )
                .order_by(ScannerAlert.last_updated_at.desc())
                .limit(1)
            )

        if detection["action"] == "escalate" and alert is not None and alert.telegram_message_ids:
            notified = await _edit_existing(alert.telegram_message_ids, message)
            telegram_message_ids = alert.telegram_message_ids
        else:
            telegram_message_ids = await _broadcast_new(message)
            notified = bool(telegram_message_ids)

        if not notified:
            continue
        sent += 1

        if alert is not None:
            async with session_factory() as session:
                row = await session.get(ScannerAlert, alert.id)
                if row is not None:
                    row.telegram_message_ids = telegram_message_ids
                await session.commit()

        alert_log_id = detection.get("alert_log_id")
        if alert_log_id is not None:
            async with session_factory() as session:
                log_row = await session.get(AlertLog, alert_log_id)
                if log_row is not None:
                    log_row.broadcast = True
                await session.commit()

    if sent:
        logger.info("Scanner notifier: %d Telegram alert(s) sent", sent)
    return sent
