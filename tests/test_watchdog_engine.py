from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.watchdog.engine import (
    WATCHDOG_CRYPTO_SYMBOLS,
    WATCHDOG_MACRO_SYMBOLS,
    WatchdogEngine,
    _is_on_cooldown,
    _trend_label,
    build_watchdog_snapshot_insight,
    macro_impact_on_crypto,
)


def _session_factory(session=None) -> tuple[MagicMock, AsyncMock]:
    session = session or AsyncMock()
    session.add = MagicMock()
    session.scalar = AsyncMock(return_value=None)
    session.scalars = AsyncMock(return_value=[])
    session.__aenter__.return_value = session
    return MagicMock(return_value=session), session


def _engine(session_factory=None, session=None) -> tuple[WatchdogEngine, dict]:
    if session_factory is None:
        session_factory, session = _session_factory(session)
    deps = {
        "market_repository": AsyncMock(),
        "global_score_engine": AsyncMock(),
        "regime_detector": AsyncMock(),
        "scenario_engine": AsyncMock(),
        "replay_engine": AsyncMock(),
        "onchain_engine": AsyncMock(),
        "whale_engine": AsyncMock(),
        "technical_engine": AsyncMock(),
        "agent_orchestrator": AsyncMock(),
        "reliability_engine": AsyncMock(),
    }
    engine = WatchdogEngine(
        session_factory,
        deps["market_repository"],
        deps["global_score_engine"],
        deps["regime_detector"],
        deps["scenario_engine"],
        deps["replay_engine"],
        deps["onchain_engine"],
        deps["whale_engine"],
        deps["technical_engine"],
        deps["agent_orchestrator"],
        deps["reliability_engine"],
        None,
    )
    return engine, deps


def test_trend_label():
    assert _trend_label(None) is None
    assert _trend_label(1.5) == "Up"
    assert _trend_label(-1.5) == "Down"
    assert _trend_label(0.1) == "Flat"


def test_macro_impact_on_crypto_is_a_documented_heuristic():
    assert macro_impact_on_crypto("DXY", 1.0) == "bearish"
    assert macro_impact_on_crypto("DXY", -1.0) == "bullish"
    assert macro_impact_on_crypto("NASDAQ", 1.0) == "bullish"
    assert macro_impact_on_crypto("NASDAQ", -1.0) == "bearish"
    assert macro_impact_on_crypto("DXY", 0.0) == "neutral"
    assert macro_impact_on_crypto("BTC", 1.0) is None
    assert macro_impact_on_crypto("DXY", None) is None


def test_is_on_cooldown():
    now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert _is_on_cooldown(None, now, 60) is False
    assert _is_on_cooldown(now - timedelta(minutes=10), now, 60) is True
    assert _is_on_cooldown(now - timedelta(minutes=90), now, 60) is False


async def test_get_current_status_unavailable_before_first_cycle():
    engine, deps = _engine()
    engine.get_latest_snapshot = AsyncMock(return_value=None)
    deps["replay_engine"].get_latest.return_value = None

    status = await engine.get_current_status()

    assert status["market_health"] == "Unknown"
    assert status["brain_status"] == "unavailable"
    assert status["replay_status"] == "unavailable"
    assert status["committee_status"] == "unavailable"
    assert status["consensus_status"] == "unavailable"


async def test_get_current_status_reflects_latest_snapshot():
    engine, deps = _engine()
    now = datetime.now(UTC)
    snapshot = SimpleNamespace(
        computed_at=now,
        scan_duration_ms=850.0,
        market_health="Healthy",
        committee_decision="BUY",
        consensus={"bullish_pct": 60.0},
    )
    engine.get_latest_snapshot = AsyncMock(return_value=snapshot)
    deps["replay_engine"].get_latest.return_value = SimpleNamespace(computed_at=now)

    status = await engine.get_current_status()

    assert status["market_health"] == "Healthy"
    assert status["brain_status"] == "ok"
    assert status["replay_status"] == "ok"
    assert status["committee_status"] == "ok"
    assert status["consensus_status"] == "ok"
    assert status["scan_duration_ms"] == 850.0


async def test_get_market_overview_reads_from_existing_engines_only():
    engine, deps = _engine()
    deps["regime_detector"].get_latest.return_value = SimpleNamespace(
        regime=SimpleNamespace(value="risk_on")
    )
    deps["global_score_engine"].get_latest.return_value = SimpleNamespace(
        trend_strength_score=60,
        confidence_score=70,
        risk_score=35,
        liquidity_score=55,
        global_score=68,
    )
    deps["technical_engine"].get_latest.return_value = SimpleNamespace(
        momentum=3.2, volatility=24.0
    )

    overview = await engine.get_market_overview()

    assert overview["regime"] == "risk_on"
    assert overview["trend"] == "Bullish"
    assert overview["trend_strength"] == 60
    assert overview["momentum"] == 3.2
    assert overview["volatility"] == 24.0
    assert overview["market_intelligence_score"] == 68
    deps["technical_engine"].get_latest.assert_awaited_once_with("BTC")


async def test_get_market_overview_none_safe_when_nothing_computed_yet():
    engine, deps = _engine()
    deps["regime_detector"].get_latest.return_value = None
    deps["global_score_engine"].get_latest.return_value = None
    deps["technical_engine"].get_latest.return_value = None

    overview = await engine.get_market_overview()

    assert overview["regime"] is None
    assert overview["trend"] is None
    assert overview["trend_strength"] is None


def _asset(symbol: str, price: float, change_pct_24h: float | None = 2.0):
    return SimpleNamespace(
        symbol=symbol, price=price, change_pct_24h=change_pct_24h, volume_24h=1000.0
    )


async def test_get_crypto_overview_reports_unavailable_for_unsynced_symbols():
    engine, deps = _engine()
    deps["market_repository"].get_latest.return_value = [_asset("BTC", 65000.0)]
    deps["market_repository"].get_history.return_value = []
    deps["technical_engine"].get_latest.return_value = None

    rows = await engine.get_crypto_overview()

    assert len(rows) == len(WATCHDOG_CRYPTO_SYMBOLS)
    btc_row = next(r for r in rows if r["symbol"] == "BTC")
    assert btc_row["available"] is True
    assert btc_row["price"] == 65000.0
    bnb_row = next(r for r in rows if r["symbol"] == "BNB")
    assert bnb_row["available"] is False


async def test_get_crypto_overview_never_fabricates_missing_symbols():
    # BNB/LINK/ADA/AVAX have no CoinGecko coverage in this codebase -- every
    # row for them must be honestly "unavailable", never a fabricated price.
    engine, deps = _engine()
    deps["market_repository"].get_latest.return_value = []
    deps["market_repository"].get_history.return_value = []
    deps["technical_engine"].get_latest.return_value = None

    rows = await engine.get_crypto_overview()

    assert all(row["available"] is False for row in rows)
    assert all("price" not in row for row in rows)


async def test_get_macro_overview_includes_impact_on_crypto():
    engine, deps = _engine()
    deps["market_repository"].get_latest.return_value = [
        SimpleNamespace(symbol="DXY", price=104.0, change_pct_24h=0.5)
    ]

    rows = await engine.get_macro_overview()

    assert len(rows) == len(WATCHDOG_MACRO_SYMBOLS)
    dxy_row = next(r for r in rows if r["symbol"] == "DXY")
    assert dxy_row["available"] is True
    assert dxy_row["impact_on_crypto"] == "bearish"
    us02y_row = next(r for r in rows if r["symbol"] == "US02Y")
    assert us02y_row["available"] is False


async def test_get_onchain_overview_never_fabricates_when_unavailable():
    engine, deps = _engine()
    deps["whale_engine"].get_snapshot.return_value = {"available": False, "reason": "no key"}
    deps["onchain_engine"].get_snapshot.return_value = {
        "available": False,
        "reason": "No on-chain data provider configured.",
        "metrics": {"exchange_netflow": None, "stablecoin_supply": None, "tvl": None},
    }

    result = await engine.get_onchain_overview()

    assert result["available"] is False
    assert result["exchange_flows"] is None
    assert result["stablecoin_flow"] is None
    assert result["tvl"] is None


async def test_get_onchain_overview_surfaces_real_whale_data_when_available():
    engine, deps = _engine()
    deps["whale_engine"].get_snapshot.return_value = {
        "available": True,
        "classification": "long_heavy",
        "funding_rate": 0.01,
        "open_interest": 5_000_000_000,
    }
    deps["onchain_engine"].get_snapshot.return_value = {
        "available": False,
        "reason": "no on-chain provider",
        "metrics": {"exchange_netflow": None, "stablecoin_supply": None, "tvl": None},
    }

    result = await engine.get_onchain_overview()

    assert result["available"] is True
    assert result["funding"] == 0.01
    assert result["open_interest"] == 5_000_000_000


async def test_get_ai_status_before_any_cycle():
    engine, _ = _engine()
    engine.get_latest_snapshot = AsyncMock(return_value=None)

    status = await engine.get_ai_status()

    assert status["computed_at"] is None
    assert status["committee_opinion"] is None


def _snapshot_for_insight(**overrides) -> SimpleNamespace:
    defaults = {
        "regime": "risk_on",
        "market_health": "Healthy",
        "risk_score": 30,
        "confidence_score": 72,
        "committee_decision": "BUY",
        "committee_confidence_pct": 72.5,
        "committee_recommendation": "BUY (high conviction)",
        "consensus": {
            "bullish_pct": 60.0,
            "bearish_pct": 20.0,
            "neutral_pct": 20.0,
            "agreement_score": 60.0,
        },
        "expected_scenario": "Soft Landing",
        "expected_scenario_pct": 40,
        "highest_risk": "Risk Off (25%) -- ...",
        "biggest_opportunity": "Soft Landing (40%) -- ...",
        "computed_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


async def test_get_ai_status_after_a_cycle():
    engine, _ = _engine()
    engine.get_latest_snapshot = AsyncMock(return_value=_snapshot_for_insight())

    status = await engine.get_ai_status()

    assert status["committee_opinion"] == "BUY (high conviction)"
    assert status["prediction_confidence"] == 72.5
    assert status["expected_scenario"] == "Soft Landing"


def test_build_watchdog_snapshot_insight_returns_empty_insight_for_none():
    insight = build_watchdog_snapshot_insight(None)

    assert insight["current_status"] is None
    assert insight["ai_conclusion"] is None
    assert insight["confidence"] is None


def test_build_watchdog_snapshot_insight_composes_from_a_real_snapshot():
    row = _snapshot_for_insight()

    insight = build_watchdog_snapshot_insight(row)

    assert "Risk On" in insight["current_status"]
    assert "risk 30/100" in insight["current_status"]
    assert insight["ai_conclusion"] == "BUY (high conviction)"
    assert insight["committee_opinion"] == "BUY (72.5%)"
    assert "Bullish 60.0%" in insight["consensus"]
    assert insight["main_opportunity"] == "Soft Landing (40%) -- ..."
    assert insight["main_risk"] == "Risk Off (25%) -- ..."
    assert insight["expected_scenario"] == "Soft Landing (40%)"
    assert insight["confidence"] == 72
    # WatchdogSnapshot never stores per-agent reasoning/evidence or a
    # similarity search -- these must stay honestly unset, not fabricated.
    assert insight["why"] is None
    assert insight["supporting_evidence"] == []
    assert insight["historical_similarity"] is None


# ---- Forecast Intelligence Upgrade: Regime-Aware Weighting -----------------


async def test_safe_reliability_uses_flat_method_without_a_live_regime():
    engine, deps = _engine()
    deps["reliability_engine"].evaluate_reliability.return_value = {"macro": 55.0}

    result = await engine._safe_reliability(None)

    assert result == {"macro": 55.0}
    deps["reliability_engine"].evaluate_reliability.assert_awaited_once()
    deps["reliability_engine"].evaluate_reliability_hierarchical.assert_not_called()


async def test_safe_reliability_uses_hierarchical_method_with_a_live_regime():
    engine, deps = _engine()
    deps["reliability_engine"].evaluate_reliability_hierarchical.return_value = {
        "macro": {"accuracy_pct": 62.0, "level": "horizon_regime", "effective_sample_size": 40},
        "technical": {"accuracy_pct": None, "level": "global", "effective_sample_size": 0},
    }

    result = await engine._safe_reliability("risk_on")

    # Adapted to the flat {agent: accuracy_pct} shape compute_consensus
    # expects -- an agent with no real accuracy_pct yet (None) is dropped,
    # never defaulted to a fabricated number.
    assert result == {"macro": 62.0}
    deps["reliability_engine"].evaluate_reliability_hierarchical.assert_awaited_once_with(
        regime="risk_on"
    )
    deps["reliability_engine"].evaluate_reliability.assert_not_called()


async def test_safe_reliability_none_on_exception():
    engine, deps = _engine()
    deps["reliability_engine"].evaluate_reliability_hierarchical.side_effect = RuntimeError(
        "db down"
    )

    assert await engine._safe_reliability("risk_on") is None


async def test_run_cycle_passes_live_regime_into_hierarchical_reliability():
    session_factory, session = _session_factory()
    engine, deps = _engine(session_factory, session)
    engine.get_latest_snapshot = AsyncMock(return_value=None)

    deps["regime_detector"].get_latest.return_value = SimpleNamespace(
        regime=SimpleNamespace(value="accumulation")
    )
    deps["global_score_engine"].get_latest.return_value = SimpleNamespace(
        global_score=70,
        trend_strength_score=60,
        risk_score=30,
        confidence_score=75,
        liquidity_score=55,
    )
    deps["scenario_engine"].get_latest.return_value = None
    deps["technical_engine"].get_latest.return_value = SimpleNamespace(volatility=24.0)
    deps["agent_orchestrator"].run_all.return_value = {}
    deps["reliability_engine"].evaluate_reliability_hierarchical.return_value = {}

    await engine.run_cycle()

    deps["reliability_engine"].evaluate_reliability_hierarchical.assert_awaited_once_with(
        regime="accumulation"
    )


async def test_run_cycle_persists_snapshot_and_detects_no_changes_on_first_cycle():
    session_factory, session = _session_factory()
    engine, deps = _engine(session_factory, session)
    engine.get_latest_snapshot = AsyncMock(return_value=None)

    deps["regime_detector"].get_latest.return_value = SimpleNamespace(
        regime=SimpleNamespace(value="risk_on")
    )
    deps["global_score_engine"].get_latest.return_value = SimpleNamespace(
        global_score=70,
        trend_strength_score=60,
        risk_score=30,
        confidence_score=75,
        liquidity_score=55,
    )
    deps["scenario_engine"].get_latest.return_value = SimpleNamespace(
        scenarios=[
            {
                "name": "Soft Landing",
                "key": "soft_landing",
                "probability_pct": 40,
                "rationale": "r",
            },
            {"name": "Risk Off", "key": "risk_off", "probability_pct": 25, "rationale": "r"},
            {
                "name": "Liquidity Expansion",
                "key": "liquidity_expansion",
                "probability_pct": 20,
                "rationale": "r",
            },
            {"name": "Black Swan", "key": "black_swan", "probability_pct": 15, "rationale": "r"},
        ]
    )
    deps["technical_engine"].get_latest.return_value = SimpleNamespace(volatility=24.0)
    deps["agent_orchestrator"].run_all.return_value = {
        "macro": SimpleNamespace(direction="bullish", confidence=70.0, summary="s"),
    }
    deps["reliability_engine"].evaluate_reliability_hierarchical.return_value = {}

    row = await engine.run_cycle()

    assert row.market_health == "Healthy"
    assert row.regime == "risk_on"
    session.add.assert_called()
    session.commit.assert_awaited()


async def test_run_cycle_notifies_telegram_for_eligible_change_only():
    session_factory, session = _session_factory()
    engine, deps = _engine(session_factory, session)

    previous_snapshot = SimpleNamespace(
        regime="risk_on",
        trend_strength_score=50,
        confidence_score=80,
        risk_score=30,
        liquidity_score=50,
        volatility=20.0,
        committee_decision="BUY",
    )
    engine.get_latest_snapshot = AsyncMock(return_value=previous_snapshot)

    deps["regime_detector"].get_latest.return_value = SimpleNamespace(
        regime=SimpleNamespace(value="risk_off")
    )
    deps["global_score_engine"].get_latest.return_value = SimpleNamespace(
        global_score=40,
        trend_strength_score=50,
        risk_score=30,
        confidence_score=80,
        liquidity_score=50,
    )
    deps["scenario_engine"].get_latest.return_value = None
    deps["technical_engine"].get_latest.return_value = SimpleNamespace(volatility=20.0)
    deps["agent_orchestrator"].run_all.return_value = {}
    deps["reliability_engine"].evaluate_reliability_hierarchical.return_value = {}

    with patch("app.telegram.broadcast.broadcast_text", AsyncMock()) as broadcast_mock:
        await engine.run_cycle()

    broadcast_mock.assert_awaited_once()
    (message,), _ = broadcast_mock.call_args
    assert "MarketRegimeChanged" in message


def _current_status(market_health="Watch") -> dict:
    return {
        "current_time": "2026-01-01T00:00:00+00:00",
        "last_update": "2026-01-01T00:00:00+00:00",
        "scan_duration_ms": 100.0,
        "market_health": market_health,
        "brain_status": "ok",
        "replay_status": "ok",
        "committee_status": "ok",
        "consensus_status": "ok",
    }


def _what_changed(events: list[dict] | None = None) -> dict:
    return {
        "available": True,
        "previous_computed_at": "2025-12-31T23:00:00+00:00",
        "current_computed_at": "2026-01-01T00:00:00+00:00",
        "fields": [],
        "events": events or [],
    }


def _ai_status(**overrides) -> dict:
    base = {
        "committee_opinion": "BUY (high conviction)",
        "consensus": None,
        "prediction_confidence": 70.0,
        "expected_scenario": "Soft Landing",
        "expected_scenario_pct": 40,
        "highest_risk": None,
        "biggest_opportunity": None,
        "computed_at": "2026-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def test_market_brief_reports_stable_conditions_when_nothing_changed():
    brief = WatchdogEngine._compose_market_brief(
        _current_status("Healthy"), _what_changed(), _ai_status()
    )

    assert brief["is_market_healthy"] is True
    assert brief["risk_direction"] == "stable"
    assert brief["ai_opinion_changed"] is False
    assert brief["biggest_changes_today"] == []
    assert "No urgent items" in brief["needs_attention"][0]


def test_market_brief_flags_rising_risk_and_committee_change():
    events = [
        {
            "event_type": "RiskIncreased",
            "message": "Risk score rose from 30 to 60.",
            "data": {"prev": 30, "curr": 60, "delta": 30},
        },
        {
            "event_type": "CommitteeChanged",
            "message": "AI Investment Committee decision changed: HOLD -> SELL.",
            "data": {"prev": "HOLD", "curr": "SELL"},
        },
    ]

    brief = WatchdogEngine._compose_market_brief(
        _current_status("Stressed"),
        _what_changed(events),
        _ai_status(highest_risk="Risk Off (55%)"),
    )

    assert brief["is_market_healthy"] is False
    assert brief["risk_direction"] == "increasing"
    assert "Risk score rose" in brief["risk_reason"]
    assert brief["ai_opinion_changed"] is True
    assert "HOLD -> SELL" in brief["ai_opinion_reason"]
    assert len(brief["biggest_changes_today"]) == 2
    # Rising risk, the committee flip, the Stressed label, and the highest
    # scenario risk should all surface as things needing attention.
    assert len(brief["needs_attention"]) == 4
