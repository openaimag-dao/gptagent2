import logging

from aiogram.exceptions import TelegramBadRequest

from app.config import get_settings
from app.database.models import Report
from app.telegram.bot import build_bot
from app.telegram.formatters import format_report

logger = logging.getLogger(__name__)


def parse_chat_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


async def broadcast_text(text: str) -> None:
    """Sends `text` to every configured Telegram chat.

    Silently does nothing if Telegram isn't configured. A failure sending
    to one chat never blocks the others. Shared by both scheduled report
    broadcasts and the Smart Alert Engine's push notifications so the
    bot-session lifecycle is only handled in one place.
    """
    settings = get_settings()
    chat_ids = parse_chat_ids(settings.telegram_broadcast_chat_ids)
    if not settings.telegram_bot_token or not chat_ids:
        logger.info("Telegram broadcast skipped (not configured)")
        return

    bot = build_bot()
    try:
        for chat_id in chat_ids:
            body = text[:4090]
            try:
                await bot.send_message(chat_id=chat_id, text=body, parse_mode="Markdown")
            except TelegramBadRequest:
                # Same Markdown-entity-parsing failure _answer() guards
                # against in handlers.py -- parse_mode=None must be passed
                # explicitly, since the Bot's own default parse_mode is
                # Markdown and an omitted parse_mode resolves to it.
                try:
                    await bot.send_message(chat_id=chat_id, text=body, parse_mode=None)
                except Exception:
                    logger.warning("Failed to broadcast to chat %s", chat_id, exc_info=True)
            except Exception:
                logger.warning("Failed to broadcast to chat %s", chat_id, exc_info=True)
    finally:
        await bot.session.close()


async def send_text_to(chat_id: int, text: str) -> bool:
    """Sends `text` to a single chat (unlike broadcast_text's "every configured
    chat") -- used by Configurable Alerts, where each rule targets only the
    chat that created it. Returns whether the send succeeded.
    """
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.info("Telegram send skipped (not configured)")
        return False

    bot = build_bot()
    try:
        body = text[:4090]
        try:
            await bot.send_message(chat_id=chat_id, text=body, parse_mode="Markdown")
        except TelegramBadRequest:
            await bot.send_message(chat_id=chat_id, text=body, parse_mode=None)
        return True
    except Exception:
        logger.warning("Failed to send to chat %s", chat_id, exc_info=True)
        return False
    finally:
        await bot.session.close()


async def send_text_to_with_id(chat_id: int, text: str) -> int | None:
    """Same send as send_text_to(), but returns the sent message's
    `message_id` (or None on failure) instead of a bool -- used by the
    Autonomous Critical Alert System, which needs the id back so a later
    escalation can edit this exact message instead of sending a new one.
    A separate function rather than changing send_text_to()'s return type,
    since Configurable Alerts already depends on that returning a bool.
    """
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.info("Telegram send skipped (not configured)")
        return None

    bot = build_bot()
    try:
        body = text[:4090]
        try:
            message = await bot.send_message(chat_id=chat_id, text=body, parse_mode="Markdown")
        except TelegramBadRequest:
            message = await bot.send_message(chat_id=chat_id, text=body, parse_mode=None)
        return message.message_id
    except Exception:
        logger.warning("Failed to send to chat %s", chat_id, exc_info=True)
        return None
    finally:
        await bot.session.close()


async def edit_text(chat_id: int, message_id: int, text: str) -> bool:
    """Edits a previously-sent message in place -- the escalation half of
    send_text_to_with_id(): an ongoing shock episode updates its existing
    Telegram message as severity increases rather than sending a new one
    each cycle. Returns whether the edit succeeded (False if the message
    was deleted, too old to edit, or Telegram isn't configured)."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        logger.info("Telegram edit skipped (not configured)")
        return False

    bot = build_bot()
    try:
        body = text[:4090]
        try:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=body, parse_mode="Markdown"
            )
        except TelegramBadRequest:
            await bot.edit_message_text(
                chat_id=chat_id, message_id=message_id, text=body, parse_mode=None
            )
        return True
    except Exception:
        logger.warning("Failed to edit message %s in chat %s", message_id, chat_id, exc_info=True)
        return False
    finally:
        await bot.session.close()


async def broadcast_report(report: Report, institutional_report: dict | None = None) -> None:
    """Sends a generated report to every configured Telegram chat.

    The report is already stored and available via the API/bot commands
    regardless of whether Telegram broadcast is configured.
    """
    await broadcast_text(format_report(report, institutional_report))
