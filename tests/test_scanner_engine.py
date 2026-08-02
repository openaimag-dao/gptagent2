from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.services.scanner.engine import MarketScannerEngine
from app.services.scanner.universe import ALWAYS_INCLUDE


def _session_factory():
    session = AsyncMock()
    session.add = MagicMock()
    session.scalar = AsyncMock(return_value=None)
    session.scalars = AsyncMock(return_value=[])
    session.get = AsyncMock(return_value=None)
    session.refresh = AsyncMock(side_effect=lambda obj: setattr(obj, "id", 1))
    session.__aenter__.return_value = session
    return MagicMock(return_value=session), session


def _engine(session_factory=None, session=None, watchdog_snapshot=None):
    if session_factory is None:
        session_factory, session = _session_factory()
    universe = AsyncMock()
    markets_client = AsyncMock()
    watchdog_engine = AsyncMock()
    watchdog_engine.get_latest_snapshot.return_value = watchdog_snapshot
    technical_engine = AsyncMock()
    technical_engine.get_latest.return_value = None
    engine = MarketScannerEngine(
        session_factory, universe, markets_client, watchdog_engine, technical_engine, None, 500
    )
    deps = {
        "universe": universe,
        "markets_client": markets_client,
        "watchdog_engine": watchdog_engine,
        "technical_engine": technical_engine,
    }
    return engine, deps, session


def _watchdog_snapshot(**overrides) -> SimpleNamespace:
    defaults = {
        "regime": "risk_off",
        "market_health": "Watch",
        "risk_score": 70,
        "confidence_score": 40,
        "trend_strength_score": 55,
        "committee_decision": "SELL",
        "committee_confidence_pct": 75.0,
        "committee_recommendation": "SELL (moderate conviction)",
        "consensus": {
            "bullish_pct": 20.0,
            "bearish_pct": 70.0,
            "neutral_pct": 10.0,
            "agreement_score": 70.0,
        },
        "expected_scenario": "Deeper Correction",
        "expected_scenario_pct": 60,
        "highest_risk": "Macro liquidity tightening",
        "biggest_opportunity": "Oversold bounce in majors",
        "computed_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _universe_entry(symbol: str, coingecko_id: str, rank: int) -> dict:
    return {"symbol": symbol, "name": symbol, "coingecko_id": coingecko_id, "market_cap_rank": rank}


def _market_coin(
    coingecko_id: str, price: float, change_24h: float, change_1h: float = 0.0
) -> dict:
    return {
        "id": coingecko_id,
        "current_price": price,
        "price_change_percentage_1h_in_currency": change_1h,
        "price_change_percentage_24h_in_currency": change_24h,
        "total_volume": 1_000_000.0,
        "market_cap": 100_000_000.0,
    }


async def test_run_cycle_with_no_symbols_returns_empty_result():
    engine, deps, _ = _engine()
    deps["universe"].get_universe.return_value = []

    result = await engine.run_cycle()

    assert result == {"processed": [], "breadth": None, "sector_breadth": [], "universe_size": 0}


async def test_run_cycle_detects_standalone_price_event():
    engine, deps, session = _engine()
    deps["universe"].get_universe.return_value = [_universe_entry("PEPE", "pepe", 200)]
    deps["markets_client"].fetch_by_ids.return_value = [_market_coin("pepe", 0.00001, 12.0)]

    result = await engine.run_cycle()

    assert result["universe_size"] == 1
    assert len(result["processed"]) == 1
    detection = result["processed"][0]
    assert detection["category"] == "price_event"
    assert detection["symbols"] == ["PEPE"]
    assert detection["tier"] == "critical"  # 12% clears the 10% "critical" rung
    assert detection["action"] == "new"
    assert detection["alert_log_id"] == 1
    session.commit.assert_awaited()


async def test_run_cycle_message_includes_key_change_since_previous_scan():
    engine, deps, session = _engine()
    deps["universe"].get_universe.return_value = [_universe_entry("PEPE", "pepe", 200)]
    deps["markets_client"].fetch_by_ids.return_value = [_market_coin("pepe", 0.000011, 12.0)]
    prior_snapshot = SimpleNamespace(
        symbol="PEPE",
        price=0.00001,
        volume_24h=1_000_000.0,
        recorded_at=datetime(2026, 1, 1, 11, 45, tzinfo=UTC),
    )
    # First session.scalars() call is the ScannerSnapshot history read,
    # second is _latest_breakout_events() -- honestly empty here since this
    # test isn't about breakout data.
    session.scalars = AsyncMock(side_effect=[[prior_snapshot], []])

    result = await engine.run_cycle()

    detection = result["processed"][0]
    # (0.000011 - 0.00001) / 0.00001 * 100 == +10.00%
    assert "Since last scan (11:45 UTC): +10.00%." in detection["message"]


async def test_run_cycle_ignores_symbols_with_no_signal():
    engine, deps, _ = _engine()
    deps["universe"].get_universe.return_value = [_universe_entry("BTC", "bitcoin", 1)]
    deps["markets_client"].fetch_by_ids.return_value = [_market_coin("bitcoin", 65000.0, 0.5)]

    result = await engine.run_cycle()

    assert result["processed"] == []


async def test_run_cycle_detects_crypto_market_shock_instead_of_individual_alerts():
    engine, deps, _ = _engine()
    # 3 of the ALWAYS_INCLUDE crypto symbols move down together at >= "important".
    shocked = ["BTC", "ETH", "SOL"]
    universe = [
        _universe_entry(symbol, ALWAYS_INCLUDE[symbol], i + 1) for i, symbol in enumerate(shocked)
    ]
    deps["universe"].get_universe.return_value = universe
    deps["markets_client"].fetch_by_ids.return_value = [
        _market_coin(ALWAYS_INCLUDE[symbol], 100.0, -6.0) for symbol in shocked
    ]

    result = await engine.run_cycle()

    categories = [d["category"] for d in result["processed"]]
    assert "crypto_market_shock" in categories
    assert "price_event" not in categories  # folded into the combined shock, not double-alerted
    shock = next(d for d in result["processed"] if d["category"] == "crypto_market_shock")
    assert set(shock["symbols"]) == set(shocked)


async def test_run_cycle_escalation_is_one_alert_not_a_new_one_each_cycle():
    session_factory, session = _session_factory()
    engine, deps, _ = _engine(session_factory, session)
    deps["universe"].get_universe.return_value = [_universe_entry("PEPE", "pepe", 200)]

    # Cycle 1: a "high" tier move creates a new active episode.
    deps["markets_client"].fetch_by_ids.return_value = [_market_coin("pepe", 1.0, 8.5)]
    first = await engine.run_cycle()
    assert first["processed"][0]["action"] == "new"

    # Cycle 2: an existing active episode of the same alert_key/tier is returned
    # by the (mocked) lookup -- a same-tier repeat must suppress, not duplicate.
    existing_row = SimpleNamespace(
        id=1,
        alert_key="scanner:price_event:PEPE:up",
        tier="high",
        active=True,
        telegram_message_ids={},
        last_updated_at=datetime.now(UTC),
    )
    session.scalar = AsyncMock(return_value=existing_row)
    deps["markets_client"].fetch_by_ids.return_value = [_market_coin("pepe", 1.0, 8.6)]
    second = await engine.run_cycle()
    assert second["processed"][0]["action"] == "suppress"
    assert second["processed"][0]["notify_eligible"] is False


async def test_ai_filter_reads_from_latest_watchdog_snapshot_not_a_fresh_agent_run():
    watchdog_snapshot = _watchdog_snapshot()
    engine, deps, _ = _engine(watchdog_snapshot=watchdog_snapshot)
    deps["universe"].get_universe.return_value = [_universe_entry("PEPE", "pepe", 200)]
    deps["markets_client"].fetch_by_ids.return_value = [_market_coin("pepe", 1.0, -9.0)]

    result = await engine.run_cycle()

    deps["watchdog_engine"].get_latest_snapshot.assert_awaited_once()
    detection = result["processed"][0]
    # A bearish move aligned with a bearish regime/committee/consensus should
    # score highly and clear the notify-eligible gate at "high"+ tier.
    assert detection["quality_score"] is not None
    assert detection["quality_score"] > 50


async def test_get_market_context_exposes_full_watchdog_snapshot():
    watchdog_snapshot = _watchdog_snapshot()
    engine, deps, _ = _engine(watchdog_snapshot=watchdog_snapshot)

    ctx = await engine.get_market_context()

    assert ctx["regime"] == "risk_off"
    assert ctx["market_health"] == "Watch"
    assert ctx["risk_score"] == 70
    assert ctx["committee_decision"] == "SELL"
    assert ctx["committee_majority_pct"] == 75.0
    assert ctx["expected_scenario"] == "Deeper Correction"
    assert ctx["highest_risk"] == "Macro liquidity tightening"
    assert ctx["biggest_opportunity"] == "Oversold bounce in majors"
    deps["watchdog_engine"].get_latest_snapshot.assert_awaited_once()


async def test_get_market_context_composes_ai_insight_from_the_same_snapshot():
    watchdog_snapshot = _watchdog_snapshot()
    engine, _, _ = _engine(watchdog_snapshot=watchdog_snapshot)

    ctx = await engine.get_market_context()

    insight = ctx["ai_insight"]
    assert insight["ai_conclusion"] == "SELL (moderate conviction)"
    assert insight["committee_opinion"] == "SELL (75.0%)"
    assert "Bullish 20.0%" in insight["consensus"]
    assert insight["main_opportunity"] == "Oversold bounce in majors"
    assert insight["main_risk"] == "Macro liquidity tightening"
    assert insight["expected_scenario"] == "Deeper Correction (60%)"
    assert insight["confidence"] == 40


async def test_get_market_context_handles_no_snapshot_yet():
    engine, _, _ = _engine(watchdog_snapshot=None)

    ctx = await engine.get_market_context()

    assert ctx == {
        "regime": None,
        "market_health": None,
        "risk_score": None,
        "confidence_score": None,
        "trend_strength_score": None,
        "committee_decision": None,
        "committee_majority_pct": None,
        "consensus": None,
        "expected_scenario": None,
        "expected_scenario_pct": None,
        "highest_risk": None,
        "biggest_opportunity": None,
        "computed_at": None,
        "ai_insight": {
            "current_status": None,
            "ai_conclusion": None,
            "why": None,
            "supporting_evidence": [],
            "committee_opinion": None,
            "consensus": None,
            "historical_similarity": None,
            "main_opportunity": None,
            "main_risk": None,
            "expected_scenario": None,
            "what_to_watch_next": None,
            "confidence": None,
        },
    }


async def test_ai_filter_handles_decimal_committee_confidence_pct_from_postgres():
    # Regression test: WatchdogSnapshot.committee_confidence_pct is a
    # Numeric(6,2) column -- asyncpg returns decimal.Decimal for it in
    # production (unlike the plain float SimpleNamespace mocks used
    # elsewhere in this file), and passing a Decimal straight into
    # score_alert_quality()'s weighted_average() raised
    # "TypeError: unsupported operand type(s) for *: 'float' and
    # 'decimal.Decimal'" on every single run_cycle() call in production,
    # silently swallowed by compute_market_scan_job's try/except so the
    # scanner never persisted a single detection.
    watchdog_snapshot = _watchdog_snapshot(committee_confidence_pct=Decimal("75.00"))
    engine, deps, _ = _engine(watchdog_snapshot=watchdog_snapshot)
    deps["universe"].get_universe.return_value = [_universe_entry("PEPE", "pepe", 200)]
    deps["markets_client"].fetch_by_ids.return_value = [_market_coin("pepe", 1.0, -9.0)]

    result = await engine.run_cycle()

    detection = result["processed"][0]
    assert detection["quality_score"] is not None


def test_engine_module_never_imports_telegram():
    import app.services.scanner.engine as engine_module

    source = open(engine_module.__file__).read()
    # The only mentions of "telegram" allowed are the docstring/field-name
    # references explaining that this module deliberately never sends one.
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith(("import app.telegram", "from app.telegram")):
            raise AssertionError(f"engine.py must never import app.telegram: {line}")


def _breakout_event(**overrides) -> SimpleNamespace:
    defaults = {
        "symbol": "BTC",
        "event_type": "breakout",
        "direction": "bullish",
        "computed_at": datetime(2026, 1, 1, 12, tzinfo=UTC),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


async def test_latest_breakout_events_returns_empty_when_none_recorded():
    engine, _, _ = _engine()

    result = await engine._latest_breakout_events()

    assert result == {}


async def test_latest_breakout_events_keeps_only_the_most_recent_per_symbol():
    session_factory, session = _session_factory()
    older = _breakout_event(
        symbol="BTC", event_type="retest", computed_at=datetime(2026, 1, 1, tzinfo=UTC)
    )
    newer = _breakout_event(
        symbol="BTC", event_type="breakout", computed_at=datetime(2026, 1, 1, 6, tzinfo=UTC)
    )
    # Query orders by computed_at desc -- newest first.
    session.scalars = AsyncMock(return_value=[newer, older])
    engine, _, _ = _engine(session_factory, session)

    result = await engine._latest_breakout_events()

    assert result == {"BTC": newer}


def test_scan_symbol_uses_breakout_engine_label_when_available():
    engine, _, _ = _engine()
    reading = {
        "symbol": "BTC",
        "price": 65000.0,
        "change_pct_1h": 0.1,
        "change_pct_24h": 1.0,
        "volume_24h": 1_000_000.0,
    }
    breakout_event = _breakout_event(event_type="false_breakout", direction="bearish")

    scan = engine._scan_symbol(reading, [], breakout_event)

    assert scan["breakout_label"] == "False Breakout (bearish)"


def test_scan_symbol_falls_back_to_new_high_low_without_a_breakout_event():
    engine, _, _ = _engine()
    history = [
        SimpleNamespace(price=100.0, volume_24h=1_000_000.0),
        SimpleNamespace(price=101.0, volume_24h=1_000_000.0),
    ]
    reading = {
        "symbol": "PEPE",
        "price": 105.0,
        "change_pct_1h": 0.1,
        "change_pct_24h": 1.0,
        "volume_24h": 1_000_000.0,
    }

    scan = engine._scan_symbol(reading, history, None)

    assert scan["breakout_label"] == "New Daily High"
