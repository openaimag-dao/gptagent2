from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.agents.base import AgentOutput
from app.services.reliability.engine import (
    AgentReliabilityEngine,
    compute_agent_vote_correlation,
    compute_hierarchical_reliability_pct,
    compute_redundancy_penalty_pct,
    compute_shrunk_reliability_pct,
)

# No-shrinkage, no-decay settings -- isolates evaluate_reliability's own
# join/scoring logic from the V9 Increment 8 estimator so pre-existing
# behavior (a lone correct call scores 100.0) stays directly assertable.
_NO_ADJUSTMENT_SETTINGS = SimpleNamespace(
    reliability_shrinkage_pseudo_count=0.0, reliability_recency_half_life_days=1e9
)


def _row(timestamp, close):
    return SimpleNamespace(timestamp=timestamp, close=close)


def _log(agent, direction, reference_timestamp, horizon_periods=1, regime_at_prediction=None):
    return SimpleNamespace(
        agent=agent,
        direction=direction,
        reference_timestamp=reference_timestamp,
        horizon_periods=horizon_periods,
        regime_at_prediction=regime_at_prediction,
    )


async def test_log_persists_only_agents_with_a_direction():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [_row(t0, 100.0)]
    outputs = {
        "macro": AgentOutput(agent="macro", summary="", direction="bullish", confidence=60.0),
        "crypto": AgentOutput(agent="crypto", summary="", direction=None, confidence=None),
    }

    session = AsyncMock()
    session.add_all = MagicMock()
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=rows)):
        engine = AgentReliabilityEngine(session_factory)
        await engine.log(outputs)

    session.add_all.assert_called_once()
    (persisted,), _ = session.add_all.call_args
    assert len(persisted) == 1
    assert persisted[0].agent == "macro"
    assert persisted[0].reference_timestamp == t0


async def test_log_captures_latest_regime_at_prediction():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [_row(t0, 100.0)]
    outputs = {"macro": AgentOutput(agent="macro", summary="", direction="bullish")}

    session = AsyncMock()
    session.add_all = MagicMock()
    session.scalar = AsyncMock(return_value=SimpleNamespace(value="risk_on"))
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=rows)):
        engine = AgentReliabilityEngine(session_factory)
        await engine.log(outputs)

    (persisted,), _ = session.add_all.call_args
    assert persisted[0].regime_at_prediction == "risk_on"


async def test_log_regime_at_prediction_none_when_no_regime_snapshot_yet():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [_row(t0, 100.0)]
    outputs = {"macro": AgentOutput(agent="macro", summary="", direction="bullish")}

    session = AsyncMock()
    session.add_all = MagicMock()
    session.scalar = AsyncMock(return_value=None)
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=rows)):
        engine = AgentReliabilityEngine(session_factory)
        await engine.log(outputs)

    (persisted,), _ = session.add_all.call_args
    assert persisted[0].regime_at_prediction is None


async def test_log_no_op_when_no_history_synced_yet():
    session_factory = AsyncMock()
    outputs = {"macro": AgentOutput(agent="macro", summary="", direction="bullish")}

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=[])):
        engine = AgentReliabilityEngine(session_factory)
        await engine.log(outputs)

    session_factory.assert_not_called()


async def test_evaluate_reliability_scores_correct_and_incorrect_calls():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    rows = [_row(t0, 100.0), _row(t1, 110.0)]  # +10% -> realized "up"

    logs = [
        _log("macro", "bullish", t0),  # predicted up -> correct
        _log("crypto", "bearish", t0),  # predicted down -> incorrect
    ]

    session = AsyncMock()
    session.scalars.return_value = logs
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    with (
        patch("app.services.reliability.engine.get_series", AsyncMock(return_value=rows)),
        patch(
            "app.services.reliability.engine.get_settings",
            return_value=_NO_ADJUSTMENT_SETTINGS,
        ),
    ):
        engine = AgentReliabilityEngine(session_factory)
        result = await engine.evaluate_reliability()

    assert result == {"macro": 100.0, "crypto": 0.0}


async def test_evaluate_reliability_skips_predictions_whose_horizon_has_not_elapsed():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [_row(t0, 100.0)]  # no target_idx exists yet
    logs = [_log("macro", "bullish", t0)]

    session = AsyncMock()
    session.scalars.return_value = logs
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=rows)):
        engine = AgentReliabilityEngine(session_factory)
        result = await engine.evaluate_reliability()

    assert result == {}


async def test_evaluate_reliability_empty_without_synced_history():
    session_factory = AsyncMock()

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=[])):
        engine = AgentReliabilityEngine(session_factory)
        result = await engine.evaluate_reliability()

    assert result == {}


async def test_evaluate_reliability_applies_shrinkage_and_decay_from_config():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    rows = [_row(t0, 100.0), _row(t1, 110.0)]  # +10% -> realized "up"
    logs = [_log("macro", "bullish", t0)]  # predicted up -> correct, but a lone call

    session = AsyncMock()
    session.scalars.return_value = logs
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=rows)):
        engine = AgentReliabilityEngine(session_factory)
        result = await engine.evaluate_reliability()  # real config defaults

    # A single evaluated call is never trusted as confidently 100% --
    # shrinkage toward the 50% prior pulls it well below the raw accuracy.
    assert 50.0 < result["macro"] < 100.0


def test_compute_shrunk_reliability_pct_empty_is_none():
    assert compute_shrunk_reliability_pct([], datetime(2026, 1, 1, tzinfo=UTC), 30.0, 10.0) is None


def test_compute_shrunk_reliability_pct_no_shrinkage_no_decay_matches_raw_average():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    results = [(True, now), (True, now), (False, now)]
    pct = compute_shrunk_reliability_pct(results, now, half_life_days=1e9, pseudo_count=0.0)
    assert pct == round(100 * 2 / 3, 1)


def test_compute_shrunk_reliability_pct_shrinks_small_sample_toward_prior():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    results = [(True, now)]
    pct = compute_shrunk_reliability_pct(results, now, half_life_days=1e9, pseudo_count=10.0)
    # (1*1 + 0.5*10) / (1 + 10) = 6/11
    assert pct == round(100 * 6 / 11, 1)
    assert 50.0 < pct < 100.0


def test_compute_shrunk_reliability_pct_large_sample_barely_shrinks():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    results = [(True, now)] * 990 + [(False, now)] * 10  # 99% raw accuracy, n=1000
    pct = compute_shrunk_reliability_pct(results, now, half_life_days=1e9, pseudo_count=10.0)
    assert pct > 98.0  # barely pulled off 99% by a large decayed sample


def test_compute_shrunk_reliability_pct_recency_decay_favors_recent_calls():
    now = datetime(2026, 2, 1, tzinfo=UTC)
    recent_correct = (True, datetime(2026, 1, 31, tzinfo=UTC))  # 1 day old
    stale_incorrect = (False, datetime(2025, 1, 1, tzinfo=UTC))  # ~1 year old
    pct = compute_shrunk_reliability_pct(
        [recent_correct, stale_incorrect], now, half_life_days=7.0, pseudo_count=0.0
    )
    # The year-old miss is decayed to near-zero weight at a 7-day half-life,
    # so the score should track the recent correct call, not a flat 50/50.
    assert pct > 90.0


# ---- POST-V9 Phase 5: compute_hierarchical_reliability_pct ----


def test_compute_hierarchical_reliability_pct_uses_horizon_regime_when_sufficient():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    keyed = {
        (None, 1, "risk_on"): [(True, now), (True, now), (False, now)],
        (None, 1, None): [(True, now)] * 10,
        (None, None, None): [(False, now)] * 10,
    }
    result = compute_hierarchical_reliability_pct(
        keyed,
        (None, 1, "risk_on"),
        now,
        half_life_days=1e9,
        pseudo_count=0.0,
        min_effective_sample=2.0,
    )
    assert result["level"] == "horizon_regime"
    assert result["accuracy_pct"] == round(100 * 2 / 3, 1)
    assert result["effective_sample_size"] == 3.0


def test_compute_hierarchical_reliability_pct_falls_back_to_horizon_when_regime_sample_too_small():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    keyed = {
        (None, 1, "risk_on"): [(True, now)],  # 1 sample, below the 2.0 threshold
        (None, 1, None): [(True, now), (True, now), (False, now)],
        (None, None, None): [(False, now)] * 10,
    }
    result = compute_hierarchical_reliability_pct(
        keyed,
        (None, 1, "risk_on"),
        now,
        half_life_days=1e9,
        pseudo_count=0.0,
        min_effective_sample=2.0,
    )
    assert result["level"] == "horizon"
    assert result["accuracy_pct"] == round(100 * 2 / 3, 1)


def test_compute_hierarchical_reliability_pct_falls_back_to_global_when_horizon_sample_too_small():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    keyed = {
        (None, 1, "risk_on"): [(True, now)],
        (None, 1, None): [(True, now)],
        (None, None, None): [(True, now), (True, now), (False, now)],
    }
    result = compute_hierarchical_reliability_pct(
        keyed,
        (None, 1, "risk_on"),
        now,
        half_life_days=1e9,
        pseudo_count=0.0,
        min_effective_sample=2.0,
    )
    assert result["level"] == "global"
    assert result["accuracy_pct"] == round(100 * 2 / 3, 1)


def test_compute_hierarchical_reliability_pct_falls_back_to_prior_when_nothing_qualifies():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    result = compute_hierarchical_reliability_pct(
        {},
        (None, 1, "risk_on"),
        now,
        half_life_days=1e9,
        pseudo_count=0.0,
        min_effective_sample=2.0,
    )
    assert result == {"accuracy_pct": 50.0, "level": "prior", "effective_sample_size": 0.0}


def test_compute_hierarchical_reliability_pct_uses_symbol_tier_when_present_and_sufficient():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    keyed = {
        ("BTC", 1, "risk_on"): [(True, now), (True, now), (True, now)],
        (None, 1, "risk_on"): [(False, now)] * 10,
        (None, 1, None): [(False, now)] * 10,
        (None, None, None): [(False, now)] * 10,
    }
    result = compute_hierarchical_reliability_pct(
        keyed,
        ("BTC", 1, "risk_on"),
        now,
        half_life_days=1e9,
        pseudo_count=0.0,
        min_effective_sample=2.0,
    )
    assert result["level"] == "symbol_horizon_regime"
    assert result["accuracy_pct"] == 100.0


def test_compute_hierarchical_reliability_pct_no_symbol_tier_attempted_when_symbol_is_none():
    # When key's symbol is None -- the live pipeline's actual state -- the
    # symbol-specific level must never be reported, even though its key
    # would collide with the horizon_regime level's key.
    now = datetime(2026, 1, 1, tzinfo=UTC)
    keyed = {(None, 1, "risk_on"): [(True, now), (True, now)]}
    result = compute_hierarchical_reliability_pct(
        keyed,
        (None, 1, "risk_on"),
        now,
        half_life_days=1e9,
        pseudo_count=0.0,
        min_effective_sample=2.0,
    )
    assert result["level"] == "horizon_regime"


# ---- POST-V9 Phase 5: AgentReliabilityEngine.evaluate_reliability_hierarchical ----


async def test_evaluate_reliability_hierarchical_conditions_on_regime():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    rows = [_row(t0, 100.0), _row(t1, 110.0)]  # +10% -> realized "up"
    # 6 correct calls: with real config defaults (half_life=30d,
    # min_effective_sample=5.0) this clears the regime-level sample floor;
    # a single call would decay-shrink all the way to the 50% prior (see
    # test_evaluate_reliability_hierarchical_falls_back_to_prior_below_min_sample).
    logs = [_log("macro", "bullish", t0, regime_at_prediction="risk_on") for _ in range(6)]

    session = AsyncMock()
    session.scalars.return_value = logs
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=rows)):
        engine = AgentReliabilityEngine(session_factory)
        result = await engine.evaluate_reliability_hierarchical(regime="risk_on")

    assert "macro" in result
    assert result["macro"]["accuracy_pct"] > 50.0
    assert result["macro"]["level"] == "horizon_regime"
    assert result["macro"]["effective_sample_size"] >= 5.0


async def test_evaluate_reliability_hierarchical_falls_back_to_prior_below_min_sample():
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    t1 = datetime(2026, 1, 2, tzinfo=UTC)
    rows = [_row(t0, 100.0), _row(t1, 110.0)]
    logs = [_log("macro", "bullish", t0, regime_at_prediction="risk_on")]  # lone call

    session = AsyncMock()
    session.scalars.return_value = logs
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=rows)):
        engine = AgentReliabilityEngine(session_factory)
        result = await engine.evaluate_reliability_hierarchical(regime="risk_on")

    # A single decayed observation never clears the default 5.0
    # min_effective_sample floor at any level -> honest 50% prior, not a
    # falsely precise 100%.
    assert result["macro"] == {"accuracy_pct": 50.0, "level": "prior", "effective_sample_size": 0.0}


async def test_evaluate_reliability_hierarchical_empty_without_synced_history():
    session_factory = AsyncMock()

    with patch("app.services.reliability.engine.get_series", AsyncMock(return_value=[])):
        engine = AgentReliabilityEngine(session_factory)
        result = await engine.evaluate_reliability_hierarchical()

    assert result == {}


def test_compute_shrunk_reliability_pct_short_half_life_ignores_stale_calls_equally_when_both_old():
    now = datetime(2026, 2, 1, tzinfo=UTC)
    both_ancient = [
        (True, datetime(2020, 1, 1, tzinfo=UTC)),
        (False, datetime(2020, 1, 1, tzinfo=UTC)),
    ]
    pct = compute_shrunk_reliability_pct(both_ancient, now, half_life_days=7.0, pseudo_count=0.0)
    # Both decayed to (numerically) zero weight equally -> falls back to the
    # 50% prior rather than a NaN/division artifact.
    assert pct == 50.0


# ---- POST-V9 Phase 6: compute_agent_vote_correlation ----

_ALTERNATING = ["bullish", "bearish", "bullish", "bearish", "neutral", "bullish"]
_OPPOSITE_OF_ALTERNATING = ["bearish", "bullish", "bearish", "bullish", "neutral", "bearish"]
_INDEPENDENT_A = ["bullish", "bullish", "bearish", "bearish", "neutral", "bullish"]
_INDEPENDENT_B = ["bearish", "bullish", "bullish", "bearish", "bullish", "bearish"]


def test_compute_agent_vote_correlation_identical_agents_is_one():
    correlation = compute_agent_vote_correlation(_ALTERNATING, _ALTERNATING, min_sample_size=3)
    assert correlation == 1.0


def test_compute_agent_vote_correlation_opposite_agents_is_negative_one():
    correlation = compute_agent_vote_correlation(
        _ALTERNATING, _OPPOSITE_OF_ALTERNATING, min_sample_size=3
    )
    assert correlation == -1.0


def test_compute_agent_vote_correlation_independent_agents_is_near_zero():
    correlation = compute_agent_vote_correlation(_INDEPENDENT_A, _INDEPENDENT_B, min_sample_size=3)
    assert correlation is not None
    assert -0.5 < correlation < 0.5


def test_compute_agent_vote_correlation_none_when_insufficient_history():
    assert compute_agent_vote_correlation(["bullish", "bearish"], ["bullish", "bearish"], 5) is None


def test_compute_agent_vote_correlation_none_when_misaligned_lengths():
    assert compute_agent_vote_correlation(["bullish", "bearish", "bullish"], ["bullish"], 1) is None


def test_compute_agent_vote_correlation_none_when_constant_series():
    # Zero variance -> mathematically undefined correlation, not a fake 0.
    constant = ["bullish"] * 5
    assert compute_agent_vote_correlation(constant, _ALTERNATING[:5], min_sample_size=3) is None


# ---- POST-V9 Phase 6: compute_redundancy_penalty_pct ----


def test_compute_redundancy_penalty_pct_scales_with_positive_correlation():
    assert compute_redundancy_penalty_pct(1.0, max_penalty_pct=30.0) == 30.0
    assert compute_redundancy_penalty_pct(0.5, max_penalty_pct=30.0) == 15.0


def test_compute_redundancy_penalty_pct_zero_for_negative_or_zero_correlation():
    assert compute_redundancy_penalty_pct(-1.0, max_penalty_pct=30.0) == 0.0
    assert compute_redundancy_penalty_pct(0.0, max_penalty_pct=30.0) == 0.0


def test_compute_redundancy_penalty_pct_zero_when_correlation_none():
    assert compute_redundancy_penalty_pct(None, max_penalty_pct=30.0) == 0.0


# ---- POST-V9 Phase 6: AgentReliabilityEngine.evaluate_agent_correlations ----


def _prediction_log(agent, direction, reference_timestamp):
    return SimpleNamespace(
        agent=agent, direction=direction, reference_timestamp=reference_timestamp
    )


async def test_evaluate_agent_correlations_identical_agents():
    timestamps = [datetime(2026, 1, i, tzinfo=UTC) for i in range(1, 7)]
    logs = [
        _prediction_log(agent, direction, ts)
        for ts, direction in zip(timestamps, _ALTERNATING, strict=True)
        for agent in ("macro", "crypto")
    ]

    session = AsyncMock()
    session.scalars.return_value = logs
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    engine = AgentReliabilityEngine(session_factory)
    result = await engine.evaluate_agent_correlations(window=10)

    pair = result[("crypto", "macro")]
    assert pair["correlation"] == 1.0
    assert pair["sample_count"] == 6
    assert pair["redundancy_penalty_pct"] > 0.0


async def test_evaluate_agent_correlations_opposite_agents_no_penalty():
    timestamps = [datetime(2026, 1, i, tzinfo=UTC) for i in range(1, 7)]
    logs = [
        _prediction_log("macro", direction, ts)
        for ts, direction in zip(timestamps, _ALTERNATING, strict=True)
    ] + [
        _prediction_log("crypto", direction, ts)
        for ts, direction in zip(timestamps, _OPPOSITE_OF_ALTERNATING, strict=True)
    ]

    session = AsyncMock()
    session.scalars.return_value = logs
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    engine = AgentReliabilityEngine(session_factory)
    result = await engine.evaluate_agent_correlations(window=10)

    pair = result[("crypto", "macro")]
    assert pair["correlation"] == -1.0
    assert pair["redundancy_penalty_pct"] == 0.0


async def test_evaluate_agent_correlations_insufficient_history_reports_none_not_omitted():
    timestamps = [datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC)]
    logs = [
        _prediction_log(agent, "bullish", ts) for ts in timestamps for agent in ("macro", "crypto")
    ]

    session = AsyncMock()
    session.scalars.return_value = logs
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    engine = AgentReliabilityEngine(session_factory)
    result = await engine.evaluate_agent_correlations(window=10)

    pair = result[("crypto", "macro")]
    assert pair["correlation"] is None
    assert pair["sample_count"] == 2
    assert pair["redundancy_penalty_pct"] == 0.0


async def test_evaluate_agent_correlations_window_bounds_shared_timestamps_considered():
    # 40 shared timestamps, but window=10 -- only the most recent 10 should
    # feed the correlation, keeping cost bounded regardless of total log
    # volume (the rolling-bounded-window requirement from the Phase 6 spec).
    day = datetime(2026, 1, 2, tzinfo=UTC) - datetime(2026, 1, 1, tzinfo=UTC)
    timestamps = [datetime(2026, 1, 1, tzinfo=UTC) + (i * day) for i in range(40)]
    logs = [
        _prediction_log(agent, "bullish" if i % 2 == 0 else "bearish", timestamps[i])
        for i in range(40)
        for agent in ("macro", "crypto")
    ]

    session = AsyncMock()
    session.scalars.return_value = logs
    session_factory = MagicMock(return_value=session)
    session.__aenter__.return_value = session

    engine = AgentReliabilityEngine(session_factory)
    result = await engine.evaluate_agent_correlations(window=10)

    assert result[("crypto", "macro")]["sample_count"] == 10
