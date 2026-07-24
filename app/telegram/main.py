import asyncio

from app.config import get_settings
from app.telegram.bot import run_bot
from app.utils.logging import configure_logging


async def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    await run_bot()


if __name__ == "__main__":
    asyncio.run(main())
