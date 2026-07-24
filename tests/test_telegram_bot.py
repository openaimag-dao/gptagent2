import pytest

from app.telegram.bot import build_bot


def test_build_bot_raises_without_token():
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        build_bot()
