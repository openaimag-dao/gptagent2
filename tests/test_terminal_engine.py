from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

from app.services.terminal.engine import TerminalEngine


def _snapshot(**overrides):
    defaults = dict(
        id=1,
        regime="bull",
        health_score=60,
        trend_strength_score=50,
        risk_score=40,
        confidence_score=70,
        consensus=None,
        portfolio_advice=None,
        computed_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    defaults.update(overrides)
    return type("FakeSnapshot", (), defaults)()


def _probability(prob_up=60, prob_down=30):
    return type("FakeProbability", (), {"prob_up_pct": prob_up, "prob_down_pct": prob_down})()


def _breakout(direction="bullish", probability_pct=70.0, event_type="breakout"):
    return type(
        "FakeBreakout",
        (),
        {"direction": direction, "probability_pct": probability_pct, "event_type": event_type},
    )()


def _advice(recommendation="BUY"):
    return type("FakeAdvice", (), {"recommendation": recommendation})()


def _ranking_snapshot(rankings):
    return type("FakeRankingSnapshot", (), {"rankings": rankings})()


def _watchdog_snapshot_for_brief(**overrides):
    defaults = dict(
        market_health="Watch",
        committee_decision="SELL",
        highest_risk="Macro liquidity tightening",
        biggest_opportunity="Oversold bounce in majors",
        expected_scenario="Deeper Correction",
        consensus={
            "bullish_pct": 20.0,
            "bearish_pct": 70.0,
            "neutral_pct": 10.0,
            "conflict_pct": 15.0,
        },
    )
    defaults.update(overrides)
    return type("FakeWatchdogSnapshot", (), defaults)()


def _scanner_alert(tier="high"):
    return type("FakeScannerAlert", (), {"tier": tier})()


def _engine(
    probability_engine=None,
    breakout_engine=None,
    portfolio_advisor=None,
    portfolio_engine=None,
    committee_engine=None,
    global_score_engine=None,
    replay_engine=None,
    ranking_engine=None,
    watchdog_engine=None,
    market_scanner_engine=None,
    session_factory=None,
) -> TerminalEngine:
    return TerminalEngine(
        session_factory or AsyncMock(),
        probability_engine or AsyncMock(),
        breakout_engine or AsyncMock(),
        portfolio_advisor or AsyncMock(),
        portfolio_engine or AsyncMock(),
        committee_engine or AsyncMock(),
        global_score_engine or AsyncMock(),
        replay_engine or AsyncMock(),
        ranking_engine or AsyncMock(),
        watchdog_engine or AsyncMock(),
        market_scanner_engine or AsyncMock(),
    )


async def test_compute_top_opportunities_skips_symbols_with_no_signal():
    probability_engine = AsyncMock()
    probability_engine.get_latest.return_value = None
    breakout_engine = AsyncMock()
    breakout_engine.get_latest.return_value = None
    portfolio_advisor = AsyncMock()
    portfolio_advisor.advise.return_value = None

    engine = _engine(
        probability_engine=probability_engine,
        breakout_engine=breakout_engine,
        portfolio_advisor=portfolio_advisor,
    )

    result = await engine.compute_top_opportunities()

    assert result == []


async def test_compute_top_opportunities_ranks_by_conviction():
    probability_engine = AsyncMock()
    breakout_engine = AsyncMock()
    portfolio_advisor = AsyncMock()

    async def get_latest_probability(symbol, timeframe):
        return {"BTC": _probability(90, 10), "ETH": _probability(50, 48), "SOL": None}[symbol]

    async def get_latest_breakout(symbol, timeframe):
        return None

    async def advise(symbol, timeframe):
        return None

    probability_engine.get_latest.side_effect = get_latest_probability
    breakout_engine.get_latest.side_effect = get_latest_breakout
    portfolio_advisor.advise.side_effect = advise

    engine = _engine(
        probability_engine=probability_engine,
        breakout_engine=breakout_engine,
        portfolio_advisor=portfolio_advisor,
    )

    result = await engine.compute_top_opportunities()

    assert [r["symbol"] for r in result] == ["BTC", "ETH"]
    assert result[0]["classification"] == "bullish"


async def test_compute_brief_assembles_all_sections():
    committee_engine = AsyncMock()
    committee_verdict = type("V", (), {"to_dict": lambda self: {"final_recommendation": "BUY"}})()
    committee_engine.convene.return_value = committee_verdict

    global_score_engine = AsyncMock()
    global_score_engine.get_latest.return_value = type(
        "GS", (), {"risk_off_score": 40, "liquidity_score": 60, "global_score": 65}
    )()

    portfolio_engine = AsyncMock()
    portfolio_engine.get_or_create.return_value = type("P", (), {"id": 1})()
    portfolio_engine.compute_health.return_value = {"empty": True, "positions": []}

    replay_engine = AsyncMock()
    replay_engine.get_latest.return_value = _snapshot()

    probability_engine = AsyncMock()
    probability_engine.get_latest.return_value = None
    breakout_engine = AsyncMock()
    breakout_engine.get_latest.return_value = None
    portfolio_advisor = AsyncMock()
    portfolio_advisor.advise.return_value = None

    watchdog_engine = AsyncMock()
    watchdog_engine.get_latest_snapshot.return_value = _watchdog_snapshot_for_brief()
    market_scanner_engine = AsyncMock()
    market_scanner_engine.get_latest_breadth.return_value = {
        "total_scanned": 500,
        "rising_count": 300,
        "falling_count": 180,
        "unchanged_count": 20,
    }
    market_scanner_engine.list_active_alerts.return_value = [
        _scanner_alert("high"),
        _scanner_alert("high"),
        _scanner_alert("critical"),
    ]

    engine = _engine(
        probability_engine=probability_engine,
        breakout_engine=breakout_engine,
        portfolio_advisor=portfolio_advisor,
        portfolio_engine=portfolio_engine,
        committee_engine=committee_engine,
        global_score_engine=global_score_engine,
        replay_engine=replay_engine,
        watchdog_engine=watchdog_engine,
        market_scanner_engine=market_scanner_engine,
    )

    fake_memory_engine = AsyncMock()
    fake_memory_engine.get_category.return_value = [
        {
            "category": "similarity",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "summary": {
                "symbol": "BTC",
                "match_timestamp": "2025-01-01T00:00:00+00:00",
                "similarity_score": 88.0,
            },
        }
    ]

    with patch("app.services.terminal.engine.MemoryEngine", return_value=fake_memory_engine):
        brief = await engine.compute_brief()

    assert brief["committee"] == {"final_recommendation": "BUY"}
    assert brief["risk"] == {"risk_off_score": 40, "liquidity_score": 60}
    assert brief["top_opportunities"] == []
    assert brief["portfolio"] == {"empty": True, "positions": []}
    assert brief["regime"] == "bull"
    # Prefers the freshly-fetched Global Market Score (65) over the possibly
    # stale Replay snapshot's copy of an earlier global_score (60).
    assert brief["health_score"] == 65
    assert brief["consensus"]["bullish_pct"] == 20.0
    assert brief["watchdog"]["market_health"] == "Watch"
    assert brief["watchdog"]["highest_risk"] == "Macro liquidity tightening"
    assert brief["scanner"]["breadth"]["rising_count"] == 300
    assert brief["scanner"]["active_alerts_count"] == 3
    assert brief["scanner"]["active_alerts_by_tier"] == {"high": 2, "critical": 1}
    assert brief["historical_intelligence"]["summary"]["symbol"] == "BTC"


async def test_compute_brief_falls_back_to_replay_health_score_without_global_score():
    committee_engine = AsyncMock()
    committee_engine.convene.return_value = None

    global_score_engine = AsyncMock()
    global_score_engine.get_latest.return_value = None

    portfolio_engine = AsyncMock()
    portfolio_engine.get_or_create.return_value = type("P", (), {"id": 1})()
    portfolio_engine.compute_health.return_value = {"empty": True, "positions": []}

    replay_engine = AsyncMock()
    replay_engine.get_latest.return_value = _snapshot(health_score=60)

    probability_engine = AsyncMock()
    probability_engine.get_latest.return_value = None
    breakout_engine = AsyncMock()
    breakout_engine.get_latest.return_value = None
    portfolio_advisor = AsyncMock()
    portfolio_advisor.advise.return_value = None

    watchdog_engine = AsyncMock()
    watchdog_engine.get_latest_snapshot.return_value = None
    market_scanner_engine = AsyncMock()
    market_scanner_engine.get_latest_breadth.return_value = None
    market_scanner_engine.list_active_alerts.return_value = []

    engine = _engine(
        probability_engine=probability_engine,
        breakout_engine=breakout_engine,
        portfolio_advisor=portfolio_advisor,
        portfolio_engine=portfolio_engine,
        committee_engine=committee_engine,
        global_score_engine=global_score_engine,
        replay_engine=replay_engine,
        watchdog_engine=watchdog_engine,
        market_scanner_engine=market_scanner_engine,
    )

    fake_memory_engine = AsyncMock()
    fake_memory_engine.get_category.return_value = []

    with patch("app.services.terminal.engine.MemoryEngine", return_value=fake_memory_engine):
        brief = await engine.compute_brief()

    assert brief["risk"] is None
    assert brief["health_score"] == 60
    # Honestly omitted, not fabricated, when nothing has been computed yet.
    assert brief["consensus"] is None
    assert brief["watchdog"] is None
    assert brief["scanner"] == {
        "breadth": None,
        "active_alerts_count": 0,
        "active_alerts_by_tier": {},
    }
    assert brief["historical_intelligence"] is None


async def test_compute_historical_comparison_none_when_no_replay_yet():
    replay_engine = AsyncMock()
    replay_engine.get_latest.return_value = None

    engine = _engine(replay_engine=replay_engine)

    result = await engine.compute_historical_comparison(days_ago=7)

    assert result is None


async def test_compute_historical_comparison_none_when_nothing_far_back_enough():
    replay_engine = AsyncMock()
    snapshot = _snapshot(id=1)
    replay_engine.get_latest.return_value = snapshot
    replay_engine.get_nearest.return_value = snapshot  # same row -- nothing further back

    engine = _engine(replay_engine=replay_engine)

    result = await engine.compute_historical_comparison(days_ago=7)

    assert result is None


async def test_compute_historical_comparison_returns_diff_when_available():
    replay_engine = AsyncMock()
    later = _snapshot(id=2, health_score=70)
    earlier = _snapshot(id=1, health_score=50)
    replay_engine.get_latest.return_value = later
    replay_engine.get_nearest.return_value = earlier

    engine = _engine(replay_engine=replay_engine)

    result = await engine.compute_historical_comparison(days_ago=7)

    assert result["days_ago"] == 7
    assert result["diff"]["health_score"]["delta"] == 20


async def test_compute_period_performance_assembles_accuracy_and_alerts():
    replay_engine = AsyncMock()
    replay_engine.get_latest.return_value = None  # historical_comparison -> None

    engine = _engine(replay_engine=replay_engine)

    evaluated = [
        {
            "reference_timestamp": datetime.now(UTC),
            "correct": True,
        },
        {
            "reference_timestamp": datetime.now(UTC),
            "correct": False,
        },
    ]

    fake_memory_engine = AsyncMock()
    fake_memory_engine.get_category.return_value = [{"summary": "x"}]

    with (
        patch(
            "app.services.terminal.engine.evaluate_predictions",
            new=AsyncMock(return_value=evaluated),
        ),
        patch("app.services.terminal.engine.MemoryEngine", return_value=fake_memory_engine),
    ):
        result = await engine.compute_period_performance(days=7)

    assert result["period_days"] == 7
    assert result["evaluated_predictions"] == 2
    assert result["accuracy_pct"] == 50.0
    assert result["alerts_count"] == 1
    assert result["historical_comparison"] is None


async def test_get_top_factors_returns_empty_when_no_ranking_computed_yet():
    ranking_engine = AsyncMock()
    ranking_engine.get_latest.return_value = None
    engine = _engine(ranking_engine=ranking_engine)

    result = await engine.get_top_factors()

    assert result == []


async def test_get_top_factors_returns_the_top_n_already_ranked_factors():
    rankings = [
        {"factor": "etf_inflow", "current_importance_pct": 12.5, "rank": 1},
        {"factor": "nasdaq_up", "current_importance_pct": 8.0, "rank": 2},
        {"factor": "fed_dovish", "current_importance_pct": 3.0, "rank": 3},
        {"factor": "vix_up", "current_importance_pct": -1.0, "rank": 4},
    ]
    ranking_engine = AsyncMock()
    ranking_engine.get_latest.return_value = _ranking_snapshot(rankings)
    engine = _engine(ranking_engine=ranking_engine)

    result = await engine.get_top_factors(limit=2)

    assert result == rankings[:2]
