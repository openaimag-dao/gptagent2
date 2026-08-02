from datetime import UTC, datetime

from app.services.replay.engine import diff_snapshots


def _snapshot(
    regime="bull",
    health_score=60,
    trend_strength_score=50,
    risk_score=40,
    confidence_score=70,
    consensus=None,
    portfolio_advice=None,
    computed_at=None,
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
        },
    )()


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
