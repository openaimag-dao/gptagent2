import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import get_settings
from app.telegram.handlers import router

logger = logging.getLogger(__name__)


def build_bot() -> Bot:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured; the Telegram bot cannot start")
    return Bot(
        token=settings.telegram_bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )


def build_dispatcher() -> Dispatcher:
    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher


async def run_bot() -> None:
    """Starts long polling. Runs forever -- intended as its own process/service."""
    bot = build_bot()
    dispatcher = build_dispatcher()
    logger.info("Starting Telegram bot (long polling)")
    await dispatcher.start_polling(bot)
