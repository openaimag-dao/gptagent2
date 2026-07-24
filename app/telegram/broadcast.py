import logging

from app.config import get_settings
from app.database.models import Report
from app.telegram.bot import build_bot
from app.telegram.formatters import format_report

logger = logging.getLogger(__name__)


def parse_chat_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    return [int(part.strip()) for part in raw.split(",") if part.strip()]


async def broadcast_report(report: Report) -> None:
    """Sends a generated report to every configured Telegram chat.

    Silently does nothing if Telegram isn't configured -- the report is
    already stored and available via the API/bot commands regardless.
    A failure sending to one chat never blocks the others.
    """
    settings = get_settings()
    chat_ids = parse_chat_ids(settings.telegram_broadcast_chat_ids)
    if not settings.telegram_bot_token or not chat_ids:
        logger.info("Telegram broadcast skipped (not configured)")
        return

    bot = build_bot()
    text = format_report(report)[:4090]
    try:
        for chat_id in chat_ids:
            try:
                await bot.send_message(chat_id=chat_id, text=text, parse_mode="Markdown")
            except Exception:
                logger.warning("Failed to broadcast report to chat %s", chat_id, exc_info=True)
    finally:
        await bot.session.close()
