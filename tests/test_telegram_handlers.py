from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage

from app.telegram.handlers import _answer


def _bad_request() -> TelegramBadRequest:
    return TelegramBadRequest(
        method=SendMessage(chat_id=1, text="x"),
        message="Bad Request: can't parse entities: Can't find end of the entity",
    )


async def test_answer_sends_with_markdown_by_default():
    message = AsyncMock()

    await _answer(message, "*bold*")

    message.answer.assert_awaited_once_with("*bold*", parse_mode="Markdown")


async def test_answer_falls_back_to_plain_text_on_bad_markdown():
    message = AsyncMock()
    message.answer.side_effect = [_bad_request(), None]

    await _answer(message, "nasdaq_up broke it")

    assert message.answer.await_count == 2
    message.answer.assert_awaited_with("nasdaq_up broke it")
