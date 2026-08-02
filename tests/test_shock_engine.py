from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.shocks.engine import CriticalAlertEngine

_SETTINGS_WITH_CHAT = SimpleNamespace(telegram_broadcast_chat_ids="123")


def _patched_settings():
    return patch("app.services.shocks.engine.get_settings", return_value=_SETTINGS_WITH_CHAT)


def _added_model_names(session) -> list[str]:
    return [call.args[0].__class__.__name__ for call in session.add.call_args_list]


def _session_factory(session):
    session.add = MagicMock()
    session.__aenter__.return_value = session
    return MagicMock(return_value=session)


def _engine(session=None, explanation_engine=None) -> tuple[CriticalAlertEngine, MagicMock]:
    session = session or AsyncMock()
    session_factory = _session_factory(session)
    engine = CriticalAlertEngine(
        session_factory,
        AsyncMock(),  # market_repository
        AsyncMock(),  # regime_detector
        AsyncMock(),  # global_score_engine
        AsyncMock(),  # scenario_engine
        AsyncMock(),  # agent_orchestrator
        AsyncMock(),  # reliability_engine
        AsyncMock(),  # similar_market_engine
        explanation_engine=explanation_engine,
    )
    return engine, session


def _envelope(symbol="BTC", pct_change=-9.0, tier="high") -> dict:
    return {
        "alert_key": f"shock:{symbol}:down",
        "category": "price_shock",
        "symbols": [symbol],
        "direction": "down",
        "raw_tier": tier,
        "readings": [
            {"symbol": symbol, "window": "15m", "pct_change": pct_change, "current_value": 60000.0}
        ],
        "quality_components": {
            "volume": 80.0,
            "volatility": 70.0,
            "regime_alignment": 100.0,
            "trend_strength": 60.0,
            "consensus_alignment": 70.0,
            "committee_alignment": 70.0,
            "historical_similarity": None,
            "risk_score": 60.0,
            "confidence_score": 60.0,
        },
        "context": {
            "regime": "risk_off",
            "trend_strength_score": 60,
            "risk_score": 60,
            "confidence_score": 60,
            "committee": None,
            "scenarios": None,
        },
    }


def _existing_row(tier="high", active=True, last_updated_at=None, message_ids=None):
    return SimpleNamespace(
        id=1,
        alert_key="shock:BTC:down",
        tier=tier,
        active=active,
        last_updated_at=last_updated_at or datetime.now(UTC) - timedelta(minutes=5),
        telegram_message_ids=message_ids or {"123": 555},
    )


async def test_new_episode_notifies_and_persists_when_tier_eligible():
    engine, session = _engine()
    session.scalar.return_value = None  # no existing active episode

    with (
        _patched_settings(),
        patch(
            "app.telegram.broadcast.send_text_to_with_id", AsyncMock(return_value=999)
        ) as mock_send,
    ):
        result = await engine._process_envelope(_envelope(tier="high"), datetime.now(UTC))

    assert result["action"] == "new"
    assert result["tier"] == "high"
    assert result["notified"] is True
    mock_send.assert_awaited()
    assert _added_model_names(session) == ["CriticalAlert", "AlertLog"]


async def test_low_tier_is_silent_mode_never_notifies():
    engine, session = _engine()
    session.scalar.return_value = None

    with (
        _patched_settings(),
        patch("app.telegram.broadcast.send_text_to_with_id", AsyncMock()) as mock_send,
    ):
        result = await engine._process_envelope(_envelope(tier="important"), datetime.now(UTC))

    assert result["tier"] == "important"
    assert result["notified"] is False
    mock_send.assert_not_awaited()
    # Silent mode still persists the episode row (so future escalation can
    # find it) -- only Telegram is skipped, not storage.
    assert _added_model_names(session) == ["CriticalAlert", "AlertLog"]


async def test_escalation_edits_existing_message_instead_of_sending_new():
    existing = _existing_row(tier="high")
    engine, session = _engine()
    session.scalar.return_value = existing
    session.get.return_value = existing

    with (
        _patched_settings(),
        patch("app.telegram.broadcast.edit_text", AsyncMock(return_value=True)) as mock_edit,
        patch("app.telegram.broadcast.send_text_to_with_id", AsyncMock()) as mock_send,
    ):
        result = await engine._process_envelope(_envelope(tier="critical"), datetime.now(UTC))

    assert result["action"] == "escalate"
    assert result["tier"] == "critical"
    mock_edit.assert_awaited_once()
    mock_send.assert_not_awaited()
    edited_text = mock_edit.call_args.args[2]
    assert "What Changed: escalated from HIGH to CRITICAL." in edited_text


async def test_same_tier_suppresses_without_any_telegram_call():
    existing = _existing_row(tier="high")
    engine, session = _engine()
    session.scalar.return_value = existing

    with (
        _patched_settings(),
        patch("app.telegram.broadcast.edit_text", AsyncMock()) as mock_edit,
        patch("app.telegram.broadcast.send_text_to_with_id", AsyncMock()) as mock_send,
    ):
        result = await engine._process_envelope(_envelope(tier="high"), datetime.now(UTC))

    assert result["action"] == "suppress"
    assert result["notified"] is False
    mock_edit.assert_not_awaited()
    mock_send.assert_not_awaited()
    # Suppress writes no CriticalAlert row -- only the always-on AlertLog audit entry.
    assert _added_model_names(session) == ["AlertLog"]


async def test_declining_tier_on_active_episode_is_suppressed_not_deescalated():
    existing = _existing_row(tier="critical")
    engine, session = _engine()
    session.scalar.return_value = existing

    with (
        _patched_settings(),
        patch("app.telegram.broadcast.send_text_to_with_id", AsyncMock()) as mock_send,
    ):
        result = await engine._process_envelope(_envelope(tier="high"), datetime.now(UTC))

    assert result["action"] == "suppress"
    mock_send.assert_not_awaited()


async def test_stale_episode_resolves_and_starts_fresh():
    stale = _existing_row(tier="high", last_updated_at=datetime.now(UTC) - timedelta(hours=3))
    engine, session = _engine()
    session.scalar.return_value = stale
    session.get.return_value = stale

    with (
        _patched_settings(),
        patch(
            "app.telegram.broadcast.send_text_to_with_id", AsyncMock(return_value=999)
        ) as mock_send,
    ):
        result = await engine._process_envelope(_envelope(tier="high"), datetime.now(UTC))

    assert result["action"] == "new"
    mock_send.assert_awaited()
    assert stale.active is False
    assert stale.resolved_at is not None


async def test_run_cycle_suppresses_individual_alerts_folded_into_multi_asset_shock():
    engine, session = _engine()
    session.scalar.return_value = None

    async def fake_cycle_context():
        return {
            "regime": "risk_off",
            "trend_strength_score": 50,
            "risk_score": 50,
            "confidence_score": 50,
            "consensus": None,
            "committee": None,
            "scenarios": None,
        }

    async def fake_window_prices(symbol):
        moves = {"BTC": -6.0, "ETH": -7.0, "SOL": -9.0}
        if symbol in moves:
            return {"15m": moves[symbol]}, [100.0, 99.0, 100.0 + moves[symbol]]
        return {"15m": None}, []

    async def fake_fear_greed():
        return {"15m": None}, []

    with (
        patch.object(engine, "_cycle_context", fake_cycle_context),
        patch.object(engine, "_window_prices", fake_window_prices),
        patch.object(engine, "_fear_greed_window_prices", fake_fear_greed),
        patch.object(engine, "_volume_change", AsyncMock(return_value=None)),
        patch.object(engine, "_historical_forward_returns", AsyncMock(return_value=None)),
        patch("app.telegram.broadcast.send_text_to_with_id", AsyncMock(return_value=1)),
        _patched_settings(),
    ):
        engine._market_repository.get_latest = AsyncMock(return_value=[])
        results = await engine.run_cycle()

    categories = [r["category"] for r in results]
    assert categories == ["multi_asset_shock"]  # BTC/ETH/SOL folded into one, not fired separately


async def test_high_tier_new_episode_appends_explanation_evidence_pack():
    explanation_engine = AsyncMock()
    explanation_engine.build.return_value = {
        "indicators": [{"name": "rsi_oversold", "triggered": True}],
        "historical_examples": [{"similarity_score": 82.0}, {"similarity_score": 90.0}],
        "supporting_news": [{"title": "x"}],
    }
    engine, session = _engine(explanation_engine=explanation_engine)
    session.scalar.return_value = None

    with (
        _patched_settings(),
        patch(
            "app.telegram.broadcast.send_text_to_with_id", AsyncMock(return_value=999)
        ) as mock_send,
    ):
        result = await engine._process_envelope(_envelope(tier="high"), datetime.now(UTC))

    explanation_engine.build.assert_awaited_once_with("BTC")
    assert "Why: Triggered: rsi oversold" in result["message"]
    assert "2 similar setups (avg 86% similar)" in result["message"]
    assert "1 supporting news item" in result["message"]
    mock_send.assert_awaited()
    sent_text = mock_send.call_args.args[1]
    assert "Why:" in sent_text


async def test_suppressed_action_does_not_call_explanation_engine():
    explanation_engine = AsyncMock()
    existing = _existing_row(tier="critical")
    engine, session = _engine(explanation_engine=explanation_engine)
    session.scalar.return_value = existing

    with (
        _patched_settings(),
        patch("app.telegram.broadcast.send_text_to_with_id", AsyncMock()),
    ):
        result = await engine._process_envelope(_envelope(tier="high"), datetime.now(UTC))

    assert result["action"] == "suppress"
    explanation_engine.build.assert_not_awaited()


async def test_low_tier_does_not_call_explanation_engine():
    explanation_engine = AsyncMock()
    engine, session = _engine(explanation_engine=explanation_engine)
    session.scalar.return_value = None

    with (
        _patched_settings(),
        patch("app.telegram.broadcast.send_text_to_with_id", AsyncMock()),
    ):
        await engine._process_envelope(_envelope(tier="important"), datetime.now(UTC))

    explanation_engine.build.assert_not_awaited()


async def test_explanation_engine_failure_does_not_break_alert_pipeline():
    explanation_engine = AsyncMock()
    explanation_engine.build.side_effect = RuntimeError("boom")
    engine, session = _engine(explanation_engine=explanation_engine)
    session.scalar.return_value = None

    with (
        _patched_settings(),
        patch(
            "app.telegram.broadcast.send_text_to_with_id", AsyncMock(return_value=999)
        ) as mock_send,
    ):
        result = await engine._process_envelope(_envelope(tier="high"), datetime.now(UTC))

    assert result["action"] == "new"
    assert result["notified"] is True
    mock_send.assert_awaited()
