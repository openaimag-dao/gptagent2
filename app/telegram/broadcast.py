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


async def broadcast_report(report: Report) -> None:
    """Sends a generated report to every configured Telegram chat.

    The report is already stored and available via the API/bot commands
    regardless of whether Telegram broadcast is configured.
    """
    await broadcast_text(format_report(report))
