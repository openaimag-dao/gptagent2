from unittest.mock import AsyncMock, patch

import pytest

from app.telegram.bot import run_bot
from app.telegram.handlers import BOT_COMMANDS


def test_build_bot_raises_without_token():
    from app.telegram.bot import build_bot

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        build_bot()


async def test_run_bot_registers_command_menu_before_polling():
    bot = AsyncMock()
    dispatcher = AsyncMock()

    with (
        patch("app.telegram.bot.build_bot", return_value=bot),
        patch("app.telegram.bot.build_dispatcher", return_value=dispatcher),
    ):
        await run_bot()

    bot.set_my_commands.assert_awaited_once()
    (commands,), kwargs = bot.set_my_commands.call_args
    assert [c.command for c in commands] == [name for name, _ in BOT_COMMANDS]
    dispatcher.start_polling.assert_awaited_once_with(bot)
