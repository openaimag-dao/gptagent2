from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.agents.base import AgentOutput
from app.services.reliability.engine import (
    AgentReliabilityEngine,
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


def _log(agent, direction, reference_timestamp, horizon_periods=1):
    return SimpleNamespace(
        agent=agent,
        direction=direction,
        reference_timestamp=reference_timestamp,
        horizon_periods=horizon_periods,
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
