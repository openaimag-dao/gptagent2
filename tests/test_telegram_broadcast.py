from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from app.telegram.broadcast import broadcast_text, parse_chat_ids


def _bad_request() -> TelegramBadRequest:
    return TelegramBadRequest(
        method=SendMessage(chat_id=1, text="x"),
        message="Bad Request: can't parse entities: Can't find end of the entity",
    )


def _settings(chat_ids: str | None = "111,222") -> SimpleNamespace:
    return SimpleNamespace(telegram_bot_token="fake-token", telegram_broadcast_chat_ids=chat_ids)


def _fake_bot() -> SimpleNamespace:
    return SimpleNamespace(send_message=AsyncMock(), session=SimpleNamespace(close=AsyncMock()))


def test_parse_chat_ids_splits_and_ints():
    assert parse_chat_ids("123, -456") == [123, -456]


def test_parse_chat_ids_empty_when_unset():
    assert parse_chat_ids(None) == []
    assert parse_chat_ids("") == []


async def test_broadcast_sends_markdown_by_default():
    bot = _fake_bot()
    with (
        patch("app.telegram.broadcast.get_settings", return_value=_settings("111")),
        patch("app.telegram.broadcast.build_bot", return_value=bot),
    ):
        await broadcast_text("*bold*")

    bot.send_message.assert_awaited_once_with(chat_id=111, text="*bold*", parse_mode="Markdown")


async def test_broadcast_falls_back_to_plain_text_on_bad_markdown():
    bot = _fake_bot()
    bot.send_message.side_effect = [_bad_request(), None]
    with (
        patch("app.telegram.broadcast.get_settings", return_value=_settings("111")),
        patch("app.telegram.broadcast.build_bot", return_value=bot),
    ):
        await broadcast_text("nasdaq_up broke it")

    assert bot.send_message.await_count == 2
    bot.send_message.assert_awaited_with(chat_id=111, text="nasdaq_up broke it", parse_mode=None)


async def test_broadcast_continues_to_next_chat_when_one_fails_entirely():
    bot = _fake_bot()
    bot.send_message.side_effect = [_bad_request(), _bad_request(), None]
    with (
        patch("app.telegram.broadcast.get_settings", return_value=_settings("111,222")),
        patch("app.telegram.broadcast.build_bot", return_value=bot),
    ):
        await broadcast_text("nasdaq_up broke it")

    assert bot.send_message.await_count == 3
    bot.send_message.assert_awaited_with(
        chat_id=222, text="nasdaq_up broke it", parse_mode="Markdown"
    )


async def test_broadcast_skipped_when_not_configured():
    bot = _fake_bot()
    with (
        patch("app.telegram.broadcast.get_settings", return_value=_settings(None)),
        patch("app.telegram.broadcast.build_bot", return_value=bot) as build_bot_mock,
    ):
        await broadcast_text("hello")

    build_bot_mock.assert_not_called()
