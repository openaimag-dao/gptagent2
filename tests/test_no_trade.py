from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.trade_setup.no_trade import (
    check_conflicting_agents,
    check_extreme_volatility,
    check_forecast_invalidated,
    check_insufficient_edge,
    check_insufficient_sample,
    check_low_probability,
    check_poor_calibration,
    check_regime_uncertainty,
    check_stale_data,
    check_weak_historical_edge,
    compute_expected_edge_pct,
    evaluate_no_trade,
    evaluate_no_trade_for_symbol,
    no_trade_result_from_payload,
    resolve_calibration_gap_for_confidence,
)


def test_check_insufficient_sample_triggers_below_minimum():
    reason = check_insufficient_sample(10, min_sample_size=20)
    assert reason is not None
    assert reason.code == "insufficient_data"


def test_check_insufficient_sample_none_when_missing():
    reason = check_insufficient_sample(None)
    assert reason is not None
    assert reason.code == "insufficient_data"


def test_check_insufficient_sample_clears_at_minimum():
    assert check_insufficient_sample(20, min_sample_size=20) is None


def test_check_low_probability_triggers_below_minimum():
    reason = check_low_probability(40.0, min_probability_pct=55.0)
    assert reason is not None
    assert reason.code == "low_probability"


def test_check_low_probability_none_when_missing():
    reason = check_low_probability(None)
    assert reason.code == "insufficient_data"


def test_check_low_probability_clears_above_minimum():
    assert check_low_probability(70.0, min_probability_pct=55.0) is None


def test_check_conflicting_agents_triggers_above_maximum():
    reason = check_conflicting_agents(60.0, max_dissent_pct=45.0)
    assert reason is not None
    assert reason.code == "conflicting_agents"


def test_check_conflicting_agents_none_when_unavailable():
    assert check_conflicting_agents(None) is None


def test_check_extreme_volatility_triggers_above_maximum():
    reason = check_extreme_volatility(20.0, max_volatility_pct=15.0)
    assert reason is not None
    assert reason.code == "extreme_volatility"


def test_check_regime_uncertainty_triggers_at_low_tier():
    # Increment 1's regime_confidence LOW tier is exactly 30.
    reason = check_regime_uncertainty(30, min_regime_confidence_pct=30.0)
    assert reason is not None
    assert reason.code == "regime_uncertainty"


def test_check_regime_uncertainty_clears_above_threshold():
    assert check_regime_uncertainty(85, min_regime_confidence_pct=30.0) is None


def test_check_poor_calibration_triggers_on_large_gap():
    reason = check_poor_calibration(35.0, max_calibration_gap_pct=20.0)
    assert reason is not None
    assert reason.code == "poor_calibration"


def test_check_poor_calibration_uses_absolute_value():
    reason = check_poor_calibration(-35.0, max_calibration_gap_pct=20.0)
    assert reason is not None


def test_check_forecast_invalidated_triggers_on_invalidated_status():
    reason = check_forecast_invalidated("INVALIDATED")
    assert reason is not None
    assert reason.code == "forecast_invalidated"


def test_check_forecast_invalidated_clears_on_active():
    assert check_forecast_invalidated("ACTIVE") is None
    assert check_forecast_invalidated(None) is None


def test_check_stale_data_triggers_beyond_max_age():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    reference = now - timedelta(minutes=200)
    reason = check_stale_data(reference, now=now, max_stale_minutes=120)
    assert reason is not None
    assert reason.code == "stale_data"


def test_check_stale_data_clears_within_max_age():
    now = datetime(2026, 1, 1, tzinfo=UTC)
    reference = now - timedelta(minutes=30)
    assert check_stale_data(reference, now=now, max_stale_minutes=120) is None


def test_check_stale_data_triggers_when_missing():
    reason = check_stale_data(None)
    assert reason.code == "stale_data"


def test_check_weak_historical_edge_triggers_below_minimum():
    reason = check_weak_historical_edge(35.0, min_historical_win_rate_pct=50.0)
    assert reason is not None
    assert reason.code == "weak_historical_edge"


def test_check_weak_historical_edge_none_when_unavailable():
    assert check_weak_historical_edge(None) is None


# ---- POST-V9 Phase 8 (F-4): expected edge ----


def test_compute_expected_edge_pct_positive_for_strong_call():
    # probability_edge = (70-50)/100 = 0.2, expected_move=5.0, R:R=2.0
    edge = compute_expected_edge_pct(70.0, 5.0, risk_reward_ratio=2.0)
    assert edge == 2.0


def test_compute_expected_edge_pct_uses_move_magnitude_regardless_of_sign():
    assert compute_expected_edge_pct(70.0, -5.0, risk_reward_ratio=2.0) == 2.0


def test_compute_expected_edge_pct_zero_at_coin_flip_probability():
    assert compute_expected_edge_pct(50.0, 5.0, risk_reward_ratio=2.0) == 0.0


def test_compute_expected_edge_pct_none_when_inputs_missing():
    assert compute_expected_edge_pct(None, 5.0) is None
    assert compute_expected_edge_pct(70.0, None) is None


def test_check_insufficient_edge_triggers_below_minimum():
    reason = check_insufficient_edge(0.1, min_expected_edge_pct=0.3)
    assert reason is not None
    assert reason.code == "insufficient_edge"


def test_check_insufficient_edge_clears_above_minimum():
    assert check_insufficient_edge(0.5, min_expected_edge_pct=0.3) is None


def test_check_insufficient_edge_none_when_unavailable():
    # Missing data is check_low_probability/check_insufficient_sample's
    # job -- this check never fires on its own for a None edge.
    assert check_insufficient_edge(None) is None


# ---- POST-V9 Phase 3/8 (F-3): calibration bucket resolution ----

_CALIBRATION_BUCKETS = [
    {
        "confidence_bucket": "40-60%",
        "calibration_gap_pct": 12.0,
        "sample_sufficiency": "reliable",
    },
    {
        "confidence_bucket": "60-80%",
        "calibration_gap_pct": -3.0,
        "sample_sufficiency": "insufficient",
    },
]


def test_resolve_calibration_gap_for_confidence_finds_matching_bucket():
    gap, sufficient = resolve_calibration_gap_for_confidence(_CALIBRATION_BUCKETS, 50.0)
    assert gap == 12.0
    assert sufficient is True


def test_resolve_calibration_gap_for_confidence_flags_insufficient_bucket():
    gap, sufficient = resolve_calibration_gap_for_confidence(_CALIBRATION_BUCKETS, 70.0)
    assert gap == -3.0
    assert sufficient is False


def test_resolve_calibration_gap_for_confidence_none_when_no_bucket_covers_it():
    gap, sufficient = resolve_calibration_gap_for_confidence(_CALIBRATION_BUCKETS, 95.0)
    assert gap is None
    assert sufficient is False


def test_resolve_calibration_gap_for_confidence_none_when_no_buckets_or_confidence():
    assert resolve_calibration_gap_for_confidence(None, 70.0) == (None, False)
    assert resolve_calibration_gap_for_confidence(_CALIBRATION_BUCKETS, None) == (None, False)


# ---- POST-V9 Phase 2 (F-1): effective vs raw probability gating ----


def test_no_trade_result_from_payload_gates_on_effective_not_raw_probability():
    # Raw probability_pct clears the 55% default minimum, but the
    # calibration/sample-size-discounted effective_confidence_pct does not.
    payload = {
        "probability_pct": 70.0,
        "confidence": {"effective_confidence_pct": 40.0},
        "sample_size": 50,
        "expected_volatility_pct": 3.0,
        "forecast_status": "ACTIVE",
        "reference_timestamp": datetime.now(UTC).isoformat(),
        "expected_change_pct": 2.0,
        "consensus": {},
    }
    result = no_trade_result_from_payload(payload, regime_confidence_pct=85)
    assert result["recommendation"] == "NO_TRADE"
    codes = [r["code"] for r in result["reasons"]]
    assert "low_probability" in codes
    assert result["effective_probability_pct"] == 40.0


def test_no_trade_result_from_payload_falls_back_to_raw_when_no_effective_confidence():
    payload = {
        "probability_pct": 70.0,
        "confidence": {},
        "sample_size": 50,
        "expected_volatility_pct": 3.0,
        "forecast_status": "ACTIVE",
        "reference_timestamp": datetime.now(UTC).isoformat(),
        "expected_change_pct": 5.0,
        "consensus": {},
    }
    result = no_trade_result_from_payload(payload, regime_confidence_pct=85)
    assert result["recommendation"] == "TRADE_OK"
    assert result["effective_probability_pct"] is None
    assert result["expected_edge_pct"] is not None


def test_no_trade_result_from_payload_wires_real_calibration_gap():
    payload = {
        "probability_pct": 70.0,
        "confidence": {"effective_confidence_pct": 70.0},
        "sample_size": 50,
        "expected_volatility_pct": 3.0,
        "forecast_status": "ACTIVE",
        "reference_timestamp": datetime.now(UTC).isoformat(),
        "expected_change_pct": 5.0,
        "consensus": {},
        "calibration": [
            {
                "confidence_bucket": "60-80%",
                "calibration_gap_pct": 25.0,
                "sample_sufficiency": "reliable",
            }
        ],
    }
    result = no_trade_result_from_payload(payload, regime_confidence_pct=85)
    assert result["calibration_gap_pct"] == 25.0
    assert result["recommendation"] == "NO_TRADE"
    codes = [r["code"] for r in result["reasons"]]
    assert "poor_calibration" in codes


def test_no_trade_result_from_payload_ignores_insufficient_calibration_bucket():
    payload = {
        "probability_pct": 70.0,
        "confidence": {"effective_confidence_pct": 70.0},
        "sample_size": 50,
        "expected_volatility_pct": 3.0,
        "forecast_status": "ACTIVE",
        "reference_timestamp": datetime.now(UTC).isoformat(),
        "expected_change_pct": 5.0,
        "consensus": {},
        "calibration": [
            {
                "confidence_bucket": "60-80%",
                "calibration_gap_pct": 90.0,  # would fail the gate if trusted
                "sample_sufficiency": "insufficient",
            }
        ],
    }
    result = no_trade_result_from_payload(payload, regime_confidence_pct=85)
    codes = [r["code"] for r in result["reasons"]]
    assert "poor_calibration" not in codes
    # The gap is still surfaced for transparency, just not gated on.
    assert result["calibration_gap_pct"] == 90.0


def test_evaluate_no_trade_trade_ok_when_everything_clears():
    result = evaluate_no_trade(
        sample_size=50,
        probability_pct=70.0,
        dissent_pct=10.0,
        expected_volatility_pct=3.0,
        regime_confidence_pct=85.0,
        calibration_gap_pct=5.0,
        forecast_status="ACTIVE",
        reference_timestamp=datetime.now(UTC),
        historical_win_rate_pct=65.0,
    )
    assert result["recommendation"] == "TRADE_OK"
    assert result["reasons"] == []


def test_evaluate_no_trade_flags_no_trade_on_any_single_trigger():
    result = evaluate_no_trade(
        sample_size=50,
        probability_pct=40.0,  # below the 55% default minimum
        dissent_pct=10.0,
        expected_volatility_pct=3.0,
        regime_confidence_pct=85.0,
    )
    assert result["recommendation"] == "NO_TRADE"
    codes = [r["code"] for r in result["reasons"]]
    assert "low_probability" in codes


def test_evaluate_no_trade_composes_multiple_reasons():
    result = evaluate_no_trade(
        sample_size=5,  # insufficient
        probability_pct=40.0,  # low
        dissent_pct=80.0,  # conflicting
    )
    codes = {r["code"] for r in result["reasons"]}
    assert {"insufficient_data", "low_probability", "conflicting_agents"} <= codes
    assert result["recommendation"] == "NO_TRADE"


def test_evaluate_no_trade_never_faked_when_data_genuinely_absent():
    # Every truly optional signal missing -- only sample_size/probability_pct
    # and a real reference_timestamp are supplied (a missing reference
    # timestamp is itself treated as a stale-data red flag, not "n/a").
    result = evaluate_no_trade(
        sample_size=50, probability_pct=70.0, reference_timestamp=datetime.now(UTC)
    )
    assert result["recommendation"] == "TRADE_OK"


async def test_evaluate_no_trade_for_symbol_returns_none_without_a_forecast():
    forecast_engine = AsyncMock()
    forecast_engine.compute.return_value = None
    with patch("app.services.forecast.engine.build_forecast_engine", return_value=forecast_engine):
        result = await evaluate_no_trade_for_symbol(MagicMock(), "BTC")
    assert result is None


async def test_evaluate_no_trade_for_symbol_composes_verdict_from_forecast_payload():
    forecast_engine = AsyncMock()
    forecast_engine.compute.return_value = {
        "sample_size": 50,
        "probability_pct": 72,
        "consensus": {"conflict_pct": 20.0},
        "expected_volatility_pct": 4.0,
        "forecast_status": "ACTIVE",
        "reference_timestamp": datetime.now(UTC).isoformat(),
        "direction": "Bullish",
    }

    regime_session = AsyncMock()
    regime_session.scalar.return_value = MagicMock(confidence_pct=85)
    regime_session.__aenter__.return_value = regime_session
    session_factory = MagicMock(return_value=regime_session)

    with patch("app.services.forecast.engine.build_forecast_engine", return_value=forecast_engine):
        result = await evaluate_no_trade_for_symbol(session_factory, "btc", "24h")

    assert result["symbol"] == "BTC"
    assert result["horizon"] == "24h"
    assert result["direction"] == "Bullish"
    assert result["probability_pct"] == 72
    assert result["recommendation"] == "TRADE_OK"


async def test_evaluate_no_trade_for_symbol_flags_no_trade_on_invalidated_forecast():
    forecast_engine = AsyncMock()
    forecast_engine.compute.return_value = {
        "sample_size": 50,
        "probability_pct": 72,
        "consensus": {},
        "expected_volatility_pct": 4.0,
        "forecast_status": "INVALIDATED",
        "reference_timestamp": datetime.now(UTC).isoformat(),
        "direction": "Bullish",
    }

    regime_session = AsyncMock()
    regime_session.scalar.return_value = None
    regime_session.__aenter__.return_value = regime_session
    session_factory = MagicMock(return_value=regime_session)

    with patch("app.services.forecast.engine.build_forecast_engine", return_value=forecast_engine):
        result = await evaluate_no_trade_for_symbol(session_factory, "BTC")

    assert result["recommendation"] == "NO_TRADE"
    assert any(r["code"] == "forecast_invalidated" for r in result["reasons"])
