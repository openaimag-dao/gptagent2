from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandObject
from aiogram.methods import SendMessage
from aiogram.types import ErrorEvent, Update

from app.telegram.handlers import (
    BOT_COMMANDS,
    _answer,
    cmd_advice,
    cmd_health,
    cmd_memory,
    cmd_portfolio,
    cmd_watchdog,
    handle_errors,
)


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


async def test_answer_truncates_to_telegram_message_cap():
    message = AsyncMock()

    await _answer(message, "x" * 5000)

    (text,), kwargs = message.answer.call_args
    assert len(text) == 4090


async def test_cmd_memory_rejects_unknown_category_without_touching_db():
    message = AsyncMock()
    command = CommandObject(args="not_a_real_category")

    await cmd_memory(message, command)

    message.answer.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert "Unknown category 'not_a_real_category'" in text


async def test_cmd_portfolio_rejects_bad_entry_price_without_crashing():
    message = AsyncMock()
    command = CommandObject(args="add BTC 1 not_a_number")
    portfolio = AsyncMock()
    portfolio.get_or_create.return_value.id = 1

    with (
        patch("app.telegram.handlers.PortfolioEngine", return_value=portfolio),
        patch("app.telegram.handlers._market_repository"),
        patch("app.telegram.handlers.get_session_factory"),
    ):
        await cmd_portfolio(message, command)

    portfolio.add_position.assert_not_awaited()
    message.answer.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert "Couldn't add position" in text


async def test_cmd_advice_reports_unavailable_without_crashing():
    message = AsyncMock()
    command = CommandObject(args="BTC 1d")
    portfolio = AsyncMock()
    portfolio.get_or_create.return_value.id = 1
    advisor = AsyncMock()
    advisor.advise.return_value = None

    with (
        patch("app.telegram.handlers.PortfolioEngine", return_value=portfolio),
        patch("app.telegram.handlers.PortfolioAdvisorEngine", return_value=advisor),
        patch("app.telegram.handlers._market_repository"),
        patch("app.telegram.handlers.get_session_factory"),
    ):
        await cmd_advice(message, command)

    advisor.advise.assert_awaited_once()
    message.answer.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert "Not enough data yet" in text
    assert "BTC/1d" in text


async def test_cmd_health_replies_without_touching_db():
    message = AsyncMock()

    await cmd_health(message)

    message.answer.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert "Bot is running" in text


async def test_cmd_watchdog_reports_no_detections_when_empty():
    message = AsyncMock()
    memory_engine = AsyncMock()
    memory_engine.get_category.return_value = []

    with (
        patch("app.telegram.handlers.MemoryEngine", return_value=memory_engine),
        patch("app.telegram.handlers.get_session_factory"),
    ):
        await cmd_watchdog(message)

    memory_engine.get_category.assert_awaited_once_with("alerts", limit=10)
    message.answer.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert "No detections logged yet" in text


async def test_handle_errors_notifies_user_instead_of_staying_silent():
    message = AsyncMock()
    update = Update.model_construct(update_id=1, message=message)
    event = ErrorEvent(update=update, exception=RuntimeError("boom"))

    await handle_errors(event)

    message.answer.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert "went wrong" in text.lower()


async def test_handle_errors_swallows_telegram_bad_request_from_notification():
    message = AsyncMock()
    message.answer.side_effect = _bad_request()
    update = Update.model_construct(update_id=1, message=message)
    event = ErrorEvent(update=update, exception=RuntimeError("boom"))

    await handle_errors(event)  # must not raise


def test_bot_commands_are_valid_telegram_command_names():
    for name, description in BOT_COMMANDS:
        assert name.islower()
        assert 1 <= len(name) <= 32
        assert all(c.isalnum() or c == "_" for c in name)
        assert 1 <= len(description) <= 256
