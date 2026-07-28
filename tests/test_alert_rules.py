from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.alerts.rules import AlertRuleEngine, evaluate_condition, is_rule_on_cooldown


def test_evaluate_condition_above():
    assert evaluate_condition(150.0, "above", 100.0) is True
    assert evaluate_condition(50.0, "above", 100.0) is False


def test_evaluate_condition_below():
    assert evaluate_condition(50.0, "below", 100.0) is True
    assert evaluate_condition(150.0, "below", 100.0) is False


def test_is_rule_on_cooldown_none_when_never_triggered():
    assert is_rule_on_cooldown(None, datetime.now(UTC), 60) is False


def test_is_rule_on_cooldown_true_within_window():
    now = datetime.now(UTC)
    assert is_rule_on_cooldown(now - timedelta(minutes=10), now, 60) is True


def test_is_rule_on_cooldown_false_after_window_elapses():
    now = datetime.now(UTC)
    assert is_rule_on_cooldown(now - timedelta(minutes=90), now, 60) is False


def _session_factory(session):
    session.add = MagicMock()
    session.__aenter__.return_value = session
    return MagicMock(return_value=session)


def _rule(**overrides):
    defaults = dict(
        id=1,
        chat_id="123",
        symbol="BTC",
        metric="price",
        operator="above",
        threshold=100.0,
        cooldown_minutes=60,
        last_triggered_at=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


async def test_create_rule_rejects_unknown_metric():
    engine = AlertRuleEngine(AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())
    with pytest.raises(ValueError):
        await engine.create_rule("123", "BTC", "nonsense", "above", 100.0)


async def test_create_rule_rejects_unknown_operator():
    engine = AlertRuleEngine(AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())
    with pytest.raises(ValueError):
        await engine.create_rule("123", "BTC", "price", "sideways", 100.0)


async def test_create_rule_persists_and_uppercases_symbol():
    session = AsyncMock()
    session_factory = _session_factory(session)

    engine = AlertRuleEngine(session_factory, AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())
    rule = await engine.create_rule("123", "btc", "price", "above", 100.0)

    assert rule.symbol == "BTC"
    assert rule.chat_id == "123"
    session.add.assert_called_once()


async def test_list_rules_returns_rows_for_chat():
    rule = _rule()
    session = AsyncMock()
    session.scalars.return_value = [rule]
    session_factory = _session_factory(session)

    engine = AlertRuleEngine(session_factory, AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())
    rules = await engine.list_rules("123")

    assert rules == [rule]


async def test_delete_rule_removes_when_owned():
    rule = _rule(chat_id="123")
    session = AsyncMock()
    session.get.return_value = rule
    session_factory = _session_factory(session)

    engine = AlertRuleEngine(session_factory, AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())
    removed = await engine.delete_rule(1, "123")

    assert removed is True
    session.delete.assert_called_once_with(rule)


async def test_delete_rule_refuses_when_not_owned():
    rule = _rule(chat_id="999")
    session = AsyncMock()
    session.get.return_value = rule
    session_factory = _session_factory(session)

    engine = AlertRuleEngine(session_factory, AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())
    removed = await engine.delete_rule(1, "123")

    assert removed is False


async def test_delete_rule_missing_returns_false():
    session = AsyncMock()
    session.get.return_value = None
    session_factory = _session_factory(session)

    engine = AlertRuleEngine(session_factory, AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())
    removed = await engine.delete_rule(1, "123")

    assert removed is False


async def test_recent_history_filters_by_chat_id_and_limits():
    logs = [
        SimpleNamespace(data={"chat_id": "123", "symbol": "BTC"}),
        SimpleNamespace(data={"chat_id": "999", "symbol": "ETH"}),
        SimpleNamespace(data={"chat_id": "123", "symbol": "SOL"}),
    ]
    session = AsyncMock()
    session.scalars.return_value = logs
    session_factory = _session_factory(session)

    engine = AlertRuleEngine(session_factory, AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())
    history = await engine.recent_history("123", limit=1)

    assert history == [{"chat_id": "123", "symbol": "BTC"}]


async def test_evaluate_all_skips_rule_on_cooldown():
    rule = _rule(last_triggered_at=datetime.now(UTC))
    session = AsyncMock()
    session.scalars.return_value = [rule]
    session_factory = _session_factory(session)

    engine = AlertRuleEngine(session_factory, AsyncMock(), AsyncMock(), AsyncMock(), AsyncMock())
    fired = await engine.evaluate_all()

    assert fired == []


async def test_evaluate_all_skips_when_metric_unavailable():
    rule = _rule()
    session = AsyncMock()
    session.scalars.return_value = [rule]
    session_factory = _session_factory(session)

    market_repository = AsyncMock()
    market_repository.get_latest.return_value = []

    engine = AlertRuleEngine(
        session_factory, market_repository, AsyncMock(), AsyncMock(), AsyncMock()
    )
    fired = await engine.evaluate_all()

    assert fired == []


async def test_evaluate_all_skips_when_not_breached():
    rule = _rule(threshold=200.0)
    session = AsyncMock()
    session.scalars.return_value = [rule]
    session_factory = _session_factory(session)

    market_repository = AsyncMock()
    market_repository.get_latest.return_value = [SimpleNamespace(symbol="BTC", price=150.0)]

    engine = AlertRuleEngine(
        session_factory, market_repository, AsyncMock(), AsyncMock(), AsyncMock()
    )
    fired = await engine.evaluate_all()

    assert fired == []


async def test_evaluate_all_fires_and_notifies_on_price_breach():
    rule = _rule()
    session = AsyncMock()
    session.scalars.return_value = [rule]
    session.get.return_value = rule
    session_factory = _session_factory(session)

    market_repository = AsyncMock()
    market_repository.get_latest.return_value = [SimpleNamespace(symbol="BTC", price=150.0)]

    engine = AlertRuleEngine(
        session_factory, market_repository, AsyncMock(), AsyncMock(), AsyncMock()
    )
    with patch("app.telegram.broadcast.send_text_to", AsyncMock(return_value=True)) as mock_send:
        fired = await engine.evaluate_all()

    assert len(fired) == 1
    assert fired[0]["value"] == 150.0
    mock_send.assert_awaited_once()
    assert rule.last_triggered_at is not None


async def test_evaluate_all_resolves_probability_edge_metric():
    rule = _rule(metric="probability_edge", threshold=10.0)
    session = AsyncMock()
    session.scalars.return_value = [rule]
    session.get.return_value = rule
    session_factory = _session_factory(session)

    probability_engine = AsyncMock()
    probability_engine.get_latest.return_value = SimpleNamespace(
        prob_up_pct=70.0, prob_down_pct=20.0
    )

    engine = AlertRuleEngine(
        session_factory, AsyncMock(), probability_engine, AsyncMock(), AsyncMock()
    )
    with patch("app.telegram.broadcast.send_text_to", AsyncMock(return_value=True)):
        fired = await engine.evaluate_all()

    assert fired[0]["value"] == 50.0


async def test_evaluate_all_resolves_breakout_probability_metric():
    rule = _rule(metric="breakout_probability", threshold=50.0)
    session = AsyncMock()
    session.scalars.return_value = [rule]
    session.get.return_value = rule
    session_factory = _session_factory(session)

    breakout_engine = AsyncMock()
    breakout_engine.get_latest.return_value = SimpleNamespace(probability_pct=65.0)

    engine = AlertRuleEngine(
        session_factory, AsyncMock(), AsyncMock(), breakout_engine, AsyncMock()
    )
    with patch("app.telegram.broadcast.send_text_to", AsyncMock(return_value=True)):
        fired = await engine.evaluate_all()

    assert fired[0]["value"] == 65.0


async def test_evaluate_all_resolves_global_score_metric():
    rule = _rule(symbol="GLOBAL", metric="risk_off_score", threshold=30.0)
    session = AsyncMock()
    session.scalars.return_value = [rule]
    session.get.return_value = rule
    session_factory = _session_factory(session)

    global_score_engine = AsyncMock()
    global_score_engine.get_latest.return_value = SimpleNamespace(
        risk_off_score=45, liquidity_score=60
    )

    engine = AlertRuleEngine(
        session_factory, AsyncMock(), AsyncMock(), AsyncMock(), global_score_engine
    )
    with patch("app.telegram.broadcast.send_text_to", AsyncMock(return_value=True)):
        fired = await engine.evaluate_all()

    assert fired[0]["value"] == 45.0
