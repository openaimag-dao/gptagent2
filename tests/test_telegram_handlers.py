from unittest.mock import AsyncMock

from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandObject
from aiogram.methods import SendMessage

from app.telegram.handlers import _answer, cmd_memory


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
    message.answer.assert_awaited_with("nasdaq_up broke it", parse_mode=None)


async def test_cmd_memory_rejects_unknown_category_without_touching_db():
    message = AsyncMock()
    command = CommandObject(args="not_a_real_category")

    await cmd_memory(message, command)

    message.answer.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert "Unknown category 'not_a_real_category'" in text
