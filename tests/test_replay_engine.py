from datetime import UTC, datetime
from unittest.mock import AsyncMock

from app.services.committee.engine import CommitteeVerdict
from app.services.replay.engine import (
    MarketReplayEngine,
    build_replay_insight,
    committee_from_snapshot,
    diff_snapshots,
)


def _replay_engine(reliability_engine=None):
    return MarketReplayEngine(
        session_factory=AsyncMock(),
        market_repository=AsyncMock(),
        news_repository=AsyncMock(),
        regime_detector=AsyncMock(),
        global_score_engine=AsyncMock(),
        agent_orchestrator=AsyncMock(),
        reliability_engine=reliability_engine or AsyncMock(),
        portfolio_advisor=AsyncMock(),
        whale_engine=AsyncMock(),
        etf_engine=AsyncMock(),
        probability_engine=AsyncMock(),
    )


def _snapshot(
    regime="bull",
    health_score=60,
    trend_strength_score=50,
    risk_score=40,
    confidence_score=70,
    consensus=None,
    portfolio_advice=None,
    computed_at=None,
    agents=None,
):
    return type(
        "FakeSnapshot",
        (),
        {
            "regime": regime,
            "health_score": health_score,
            "trend_strength_score": trend_strength_score,
            "risk_score": risk_score,
            "confidence_score": confidence_score,
            "consensus": consensus,
            "portfolio_advice": portfolio_advice,
            "computed_at": computed_at or datetime(2026, 1, 1, tzinfo=UTC),
            "agents": agents,
        },
    )()


def _agent_dict(agent, summary, direction, confidence):
    return {
        "agent": agent,
        "summary": summary,
        "data": {},
        "generated_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        "direction": direction,
        "confidence": confidence,
    }


def _consensus_dict(**overrides):
    base = {
        "bullish_pct": 66.7,
        "bearish_pct": 33.3,
        "neutral_pct": 0.0,
        "agreement_score": 66.7,
        "conflict_pct": 33.3,
        "bullish_agents": ["macro", "sentiment"],
        "bearish_agents": ["technical"],
        "neutral_agents": [],
        "unavailable_agents": [],
        "agent_weights": {"macro": 40.0, "sentiment": 26.7, "technical": 33.3},
        "agent_evidence": {"macro": "macro evidence", "sentiment": "sentiment evidence"},
        # to_dict() also emits these computed @property fields -- committee_
        # from_snapshot() must tolerate and discard them, not pass them to
        # the ConsensusResult constructor.
        "strongest_agent": "macro",
        "invalidation_risk": "If macro flips, agreement drops to 33.3%.",
        "computed_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
    }
    base.update(overrides)
    return base


def _agents_dict():
    return {
        "macro": _agent_dict("macro", "Macro summary bullish.", "bullish", 80.0),
        "sentiment": _agent_dict("sentiment", "Sentiment summary bullish.", "bullish", 60.0),
        "technical": _agent_dict("technical", "Technical summary bearish.", "bearish", 55.0),
    }


def test_diff_snapshots_reports_regime_change():
    earlier = _snapshot(regime="bull", computed_at=datetime(2026, 1, 1, tzinfo=UTC))
    later = _snapshot(regime="bear", computed_at=datetime(2026, 1, 1, 1, tzinfo=UTC))

    result = diff_snapshots(earlier, later)

    assert result["regime"] == {"from": "bull", "to": "bear", "changed": True}


def test_diff_snapshots_reports_no_regime_change():
    earlier = _snapshot(regime="bull")
    later = _snapshot(regime="bull")

    result = diff_snapshots(earlier, later)

    assert result["regime"]["changed"] is False


def test_diff_snapshots_computes_score_deltas():
    earlier = _snapshot(health_score=40, risk_score=30)
    later = _snapshot(health_score=60, risk_score=50)

    result = diff_snapshots(earlier, later)

    assert result["health_score"]["delta"] == 20
    assert result["risk_score"]["delta"] == 20


def test_diff_snapshots_honestly_reports_none_delta_when_either_side_missing():
    earlier = _snapshot(trend_strength_score=None)
    later = _snapshot(trend_strength_score=50)

    result = diff_snapshots(earlier, later)

    assert result["trend_strength_score"]["delta"] is None
    assert result["trend_strength_score"]["from"] is None
    assert result["trend_strength_score"]["to"] == 50


def test_diff_snapshots_includes_consensus_and_portfolio_advice_raw():
    earlier = _snapshot(
        consensus={"bullish_pct": 30.0}, portfolio_advice={"recommendation": "HOLD"}
    )
    later = _snapshot(consensus={"bullish_pct": 70.0}, portfolio_advice={"recommendation": "BUY"})

    result = diff_snapshots(earlier, later)

    assert result["consensus"]["from"]["bullish_pct"] == 30.0
    assert result["consensus"]["to"]["bullish_pct"] == 70.0
    assert result["portfolio_advice"]["to"]["recommendation"] == "BUY"
    # Partial fixture consensus dicts (missing agreement_score) -- honestly
    # None rather than crashing or guessing a trend.
    assert result["consensus_evolution"] is None


def test_diff_snapshots_derives_consensus_evolution_when_both_sides_are_full_dicts():
    earlier = _snapshot(
        consensus={
            "agreement_score": 60.0,
            "bullish_pct": 60.0,
            "bearish_pct": 40.0,
            "strongest_agent": "macro",
        }
    )
    later = _snapshot(
        consensus={
            "agreement_score": 75.0,
            "bullish_pct": 75.0,
            "bearish_pct": 25.0,
            "strongest_agent": "sentiment",
        }
    )

    result = diff_snapshots(earlier, later)

    evolution = result["consensus_evolution"]
    assert evolution["agreement_score_delta"] == 15.0
    assert evolution["strongest_agent_changed"] is True
    assert "macro to sentiment" in evolution["summary"]


def test_diff_snapshots_includes_both_timestamps():
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 1, 1, 1, tzinfo=UTC)
    earlier = _snapshot(computed_at=t1)
    later = _snapshot(computed_at=t2)

    result = diff_snapshots(earlier, later)

    assert result["earlier_computed_at"] == t1.isoformat()
    assert result["later_computed_at"] == t2.isoformat()


def test_committee_from_snapshot_returns_none_when_snapshot_predates_tracking():
    row = _snapshot(agents=None, consensus=None)

    assert committee_from_snapshot(row) is None


def test_committee_from_snapshot_returns_none_when_only_agents_present():
    row = _snapshot(agents=_agents_dict(), consensus=None)

    assert committee_from_snapshot(row) is None


def test_committee_from_snapshot_reconstructs_a_real_verdict():
    row = _snapshot(agents=_agents_dict(), consensus=_consensus_dict())

    verdict = committee_from_snapshot(row)

    assert isinstance(verdict, CommitteeVerdict)
    assert verdict.majority_decision == "BUY"
    assert verdict.majority_pct == 66.7
    assert {e["agent"] for e in verdict.supporting_evidence} == {"macro", "sentiment"}


def test_committee_from_snapshot_tolerates_computed_property_fields_in_stored_dict():
    # ConsensusResult.to_dict() includes strongest_agent/invalidation_risk as
    # computed @property output -- committee_from_snapshot() must not pass
    # them back into the ConsensusResult constructor.
    row = _snapshot(
        agents=_agents_dict(),
        consensus=_consensus_dict(strongest_agent="macro", invalidation_risk="some risk text"),
    )

    verdict = committee_from_snapshot(row)

    assert verdict is not None


def test_build_replay_insight_composes_current_status_and_consensus():
    row = _snapshot(regime="bull_market", agents=_agents_dict(), consensus=_consensus_dict())
    committee = committee_from_snapshot(row)

    insight = build_replay_insight(row, committee, historical_lesson=None)

    assert "Bull Market" in insight["current_status"]
    assert "health 60/100" in insight["current_status"]
    assert "Bullish 66.7%" in insight["consensus"]
    assert insight["confidence"] == 70


def test_build_replay_insight_uses_committee_fields_when_committee_present():
    row = _snapshot(agents=_agents_dict(), consensus=_consensus_dict())
    committee = committee_from_snapshot(row)

    insight = build_replay_insight(row, committee, historical_lesson=None)

    assert insight["ai_conclusion"] == committee.final_recommendation
    assert insight["why"] == committee.reasoning
    assert "BUY" in insight["committee_opinion"]
    assert len(insight["supporting_evidence"]) == len(committee.supporting_evidence)


def test_build_replay_insight_never_fabricates_committee_fields_when_committee_is_none():
    row = _snapshot(agents=None, consensus=None)

    insight = build_replay_insight(row, committee=None, historical_lesson=None)

    assert insight["ai_conclusion"] is None
    assert insight["why"] is None
    assert insight["committee_opinion"] is None
    assert insight["supporting_evidence"] == []


def test_build_replay_insight_uses_historical_lesson_main_lesson():
    row = _snapshot(agents=None, consensus=None)

    insight = build_replay_insight(
        row, committee=None, historical_lesson={"main_lesson": "Similar to 2024 rally."}
    )

    assert insight["historical_similarity"] == "Similar to 2024 rally."


def test_build_replay_insight_never_fabricates_historical_similarity_when_lesson_is_none():
    row = _snapshot(agents=None, consensus=None)

    insight = build_replay_insight(row, committee=None, historical_lesson=None)

    assert insight["historical_similarity"] is None


# ---- Forecast Intelligence Upgrade: Regime-Aware Weighting -----------------


async def test_safe_reliability_uses_flat_method_without_a_live_regime():
    reliability_engine = AsyncMock()
    reliability_engine.evaluate_reliability.return_value = {"macro": 55.0}
    engine = _replay_engine(reliability_engine)

    result = await engine._safe_reliability(None)

    assert result == {"macro": 55.0}
    reliability_engine.evaluate_reliability.assert_awaited_once()
    reliability_engine.evaluate_reliability_hierarchical.assert_not_called()


async def test_safe_reliability_uses_hierarchical_method_with_a_live_regime():
    reliability_engine = AsyncMock()
    reliability_engine.evaluate_reliability_hierarchical.return_value = {
        "macro": {"accuracy_pct": 62.0, "level": "regime", "effective_sample_size": 30},
        "crypto": {"accuracy_pct": None, "level": "insufficient_data", "effective_sample_size": 2},
    }
    engine = _replay_engine(reliability_engine)

    result = await engine._safe_reliability("risk_off")

    assert result == {"macro": 62.0}
    reliability_engine.evaluate_reliability_hierarchical.assert_awaited_once_with(regime="risk_off")


async def test_safe_reliability_survives_reliability_engine_failure():
    reliability_engine = AsyncMock()
    reliability_engine.evaluate_reliability_hierarchical.side_effect = RuntimeError("db down")
    engine = _replay_engine(reliability_engine)

    result = await engine._safe_reliability("bull")

    assert result is None
