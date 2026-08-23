from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandObject
from aiogram.methods import SendMessage
from aiogram.types import ErrorEvent, Update

from app.telegram.handlers import (
    BOT_COMMANDS,
    _answer,
    _normalize_dashes,
    cmd_advice,
    cmd_health,
    cmd_memory,
    cmd_move_alert,
    cmd_portfolio,
    cmd_scanner,
    cmd_set_alert,
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


async def test_cmd_watchdog_events_reports_no_detections_when_empty():
    # v5.4 moved the original alert-history-only view from bare /watchdog
    # to /watchdog events -- this test now exercises that subcommand,
    # preserving the original behavior it used to pin at the top level.
    message = AsyncMock()
    command = CommandObject(args="events")
    watchdog_engine = AsyncMock()
    watchdog_engine.get_alert_history.return_value = []

    with patch("app.telegram.handlers.build_watchdog_engine", return_value=watchdog_engine):
        await cmd_watchdog(message, command)

    watchdog_engine.get_alert_history.assert_awaited_once_with(limit=10)
    message.answer.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert "No detections logged yet" in text


def _watchdog_dashboard_stub() -> dict:
    return {
        "current_status": {
            "current_time": "2026-01-01T00:00:00+00:00",
            "last_update": None,
            "scan_duration_ms": None,
            "market_health": "Unknown",
            "brain_status": "unavailable",
            "replay_status": "unavailable",
            "committee_status": "unavailable",
            "consensus_status": "unavailable",
        },
        "market_brief": {
            "is_market_healthy": None,
            "market_health_label": "Unknown",
            "risk_direction": "stable",
            "risk_reason": "No material risk-score change since the last cycle.",
            "ai_opinion_changed": False,
            "ai_opinion_reason": "Committee opinion unchanged: no verdict yet.",
            "biggest_changes_today": [],
            "needs_attention": [
                "No urgent items -- market conditions are stable since the last cycle."
            ],
            "computed_at": None,
        },
        "market_overview": {
            "regime": None,
            "trend": None,
            "trend_strength": None,
            "momentum": None,
            "volatility": None,
            "confidence": None,
            "risk_score": None,
            "liquidity_score": None,
            "market_intelligence_score": None,
        },
        "crypto_overview": [],
        "macro_overview": [],
        "onchain_overview": {"available": False, "reason": None},
        "ai_status": {
            "committee_opinion": None,
            "consensus": None,
            "prediction_confidence": None,
            "expected_scenario": None,
            "expected_scenario_pct": None,
            "highest_risk": None,
            "biggest_opportunity": None,
            "computed_at": None,
        },
        "what_changed": {"available": False, "fields": [], "events": []},
        "provider_status": [],
        "alert_history": [],
    }


async def test_cmd_watchdog_no_args_returns_full_dashboard():
    message = AsyncMock()
    command = CommandObject(args=None)
    watchdog_engine = AsyncMock()
    watchdog_engine.get_dashboard.return_value = _watchdog_dashboard_stub()

    with (
        patch("app.telegram.handlers.build_watchdog_engine", return_value=watchdog_engine),
        patch("app.telegram.handlers._watchdog_next_scan", AsyncMock(return_value=None)),
    ):
        await cmd_watchdog(message, command)

    watchdog_engine.get_dashboard.assert_awaited_once()
    message.answer.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert "CURRENT MARKET STATUS" in text
    assert "MARKET OVERVIEW" in text


def _scanner_alert_row():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    return SimpleNamespace(
        alert_key="scanner:price_event:BTC:up",
        category="price_event",
        tier="high",
        symbols=["BTC"],
        message="BTC +9.00% (24h)",
        active=True,
        last_updated_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


async def test_cmd_scanner_movers_subcommand():
    message = AsyncMock()
    command = CommandObject(args="movers")
    engine = AsyncMock()
    engine.get_latest_breadth.return_value = None

    with patch("app.telegram.handlers.build_market_scanner_engine", return_value=engine):
        await cmd_scanner(message, command)

    engine.get_latest_breadth.assert_awaited_once()
    message.answer.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert "TOP MOVERS" in text
    assert "No scan data yet" in text


async def test_cmd_scanner_sectors_subcommand():
    message = AsyncMock()
    command = CommandObject(args="sectors")
    engine = AsyncMock()
    engine.get_latest_sector_breadth.return_value = []

    with patch("app.telegram.handlers.build_market_scanner_engine", return_value=engine):
        await cmd_scanner(message, command)

    engine.get_latest_sector_breadth.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert "No sector data yet" in text


async def test_cmd_scanner_detections_subcommand_serializes_rows():
    message = AsyncMock()
    command = CommandObject(args="detections")
    engine = AsyncMock()
    engine.list_recent_alerts.return_value = [_scanner_alert_row()]

    with patch("app.telegram.handlers.build_market_scanner_engine", return_value=engine):
        await cmd_scanner(message, command)

    engine.list_recent_alerts.assert_awaited_once_with(limit=20)
    (text,), kwargs = message.answer.call_args
    assert "BTC" in text
    assert "[HIGH]" in text


async def test_cmd_scanner_pending_subcommand():
    message = AsyncMock()
    command = CommandObject(args="pending")
    engine = AsyncMock()
    engine.list_active_alerts.return_value = []

    with patch("app.telegram.handlers.build_market_scanner_engine", return_value=engine):
        await cmd_scanner(message, command)

    engine.list_active_alerts.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert "No detections logged yet" in text


async def test_cmd_scanner_no_args_returns_combined_dashboard():
    message = AsyncMock()
    command = CommandObject(args=None)
    engine = AsyncMock()
    engine.get_latest_breadth.return_value = None
    engine.get_latest_sector_breadth.return_value = []
    engine.list_active_alerts.return_value = []
    engine.list_suppressed_alerts.return_value = []
    engine.get_market_context.return_value = {}

    with patch("app.telegram.handlers.build_market_scanner_engine", return_value=engine):
        await cmd_scanner(message, command)

    engine.list_suppressed_alerts.assert_awaited_once_with(limit=50)
    engine.get_market_context.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert "MARKET SCANNER" in text


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


def test_normalize_dashes_converts_unicode_minus_variants_to_ascii_hyphen():
    for dash in "‐‑‒–—−":
        result = _normalize_dashes(f"BTC change_pct_24h below {dash}3")
        assert result == "BTC change_pct_24h below -3"
    assert _normalize_dashes("BTC price above 70000") == "BTC price above 70000"


# Root-cause regression for the bug the user hit live: a phone keyboard's
# "smart punctuation" rewrote the "-3" they typed into an en dash, and
# float("–3") raised ValueError, so /setalert BTC change_pct_24h below -3
# failed with "Threshold and cooldown minutes must be numbers." even
# though the command itself was correct.
async def test_cmd_set_alert_accepts_a_unicode_en_dash_negative_threshold():
    message = AsyncMock()
    message.chat.id = 12345
    command = CommandObject(args="BTC change_pct_24h below –3")
    engine = AsyncMock()
    engine.create_rule.return_value = SimpleNamespace(
        id=1,
        symbol="BTC",
        metric="change_pct_24h",
        operator="below",
        threshold=-3.0,
        cooldown_minutes=60,
    )

    with patch("app.telegram.handlers.build_alert_rule_engine", return_value=engine):
        await cmd_set_alert(message, command)

    engine.create_rule.assert_awaited_once_with("12345", "BTC", "change_pct_24h", "below", -3.0, 60)
    message.answer.assert_awaited_once()
    (text,), kwargs = message.answer.call_args
    assert "must be numbers" not in text


async def test_cmd_move_alert_creates_both_directions_without_a_typed_minus_sign():
    message = AsyncMock()
    message.chat.id = 12345
    command = CommandObject(args="BTC 3")
    engine = AsyncMock()
    up_rule = SimpleNamespace(id=1, symbol="BTC")
    down_rule = SimpleNamespace(id=2, symbol="BTC")
    engine.create_rule.side_effect = [up_rule, down_rule]

    with patch("app.telegram.handlers.build_alert_rule_engine", return_value=engine):
        await cmd_move_alert(message, command)

    assert engine.create_rule.await_args_list[0].args == (
        "12345",
        "BTC",
        "change_pct_24h",
        "above",
        3.0,
        60,
    )
    assert engine.create_rule.await_args_list[1].args == (
        "12345",
        "BTC",
        "change_pct_24h",
        "below",
        -3.0,
        60,
    )
    (text,), kwargs = message.answer.call_args
    assert "Rule #1" in text and "Rule #2" in text


async def test_cmd_move_alert_rejects_non_positive_pct():
    message = AsyncMock()
    command = CommandObject(args="BTC 0")

    await cmd_move_alert(message, command)

    (text,), kwargs = message.answer.call_args
    assert "positive" in text.lower()


async def test_cmd_move_alert_shows_usage_when_args_missing():
    message = AsyncMock()
    command = CommandObject(args=None)

    await cmd_move_alert(message, command)

    (text,), kwargs = message.answer.call_args
    assert "Usage: /movealert" in text
