from app.services.alerts.detectors import (
    detect_correlation_break,
    detect_dxy_reversal,
    detect_etf_milestone,
    detect_fed_event_approaching,
    detect_liquidity_change,
    detect_regime_change,
    detect_whale_accumulation,
)


def test_regime_change_fires_on_transition():
    result = detect_regime_change("risk_on", "risk_off")
    assert result["alert_type"] == "regime_change"
    assert "risk_on -> risk_off" in result["message"]


def test_regime_change_none_when_unchanged():
    assert detect_regime_change("risk_on", "risk_on") is None


def test_regime_change_none_on_first_ever_reading():
    assert detect_regime_change(None, "risk_on") is None


def test_correlation_break_fires_on_large_delta():
    result = detect_correlation_break("BTC", "NASDAQ", 30, 0.6, 0.1)
    assert result["alert_type"] == "correlation_break"
    assert result["confidence_pct"] > 0


def test_correlation_break_fires_on_sign_flip():
    result = detect_correlation_break("BTC", "NASDAQ", 30, 0.2, -0.15)
    assert result is not None


def test_correlation_break_none_for_small_stable_move():
    assert detect_correlation_break("BTC", "NASDAQ", 30, 0.5, 0.55) is None


def test_dxy_reversal_fires_on_sign_flip():
    result = detect_dxy_reversal(0.5, -0.3)
    assert result["alert_type"] == "dxy_reversal"


def test_dxy_reversal_none_without_sign_flip():
    assert detect_dxy_reversal(0.5, 0.8) is None


def test_dxy_reversal_none_for_tiny_flip():
    assert detect_dxy_reversal(0.01, -0.01) is None


def test_whale_accumulation_never_fires_when_unavailable():
    assert detect_whale_accumulation({"available": False}) is None


def test_whale_accumulation_fires_when_classified():
    result = detect_whale_accumulation({"available": True, "classification": "accumulation"})
    assert result["alert_type"] == "whale_accumulation"


def test_etf_milestone_fires_on_new_bullish_lean():
    result = detect_etf_milestone(
        None,
        {"available": True, "classification": "leaning_institutional_buying", "items_analyzed": 10},
    )
    assert result["alert_type"] == "etf_milestone"


def test_etf_milestone_none_when_unchanged():
    proxy = {
        "available": True,
        "classification": "leaning_institutional_buying",
        "items_analyzed": 10,
    }
    assert detect_etf_milestone("leaning_institutional_buying", proxy) is None


def test_liquidity_change_fires_on_big_move():
    result = detect_liquidity_change(40, 70)
    assert result["alert_type"] == "liquidity_change"
    assert "improving" in result["message"]


def test_liquidity_change_none_on_small_move():
    assert detect_liquidity_change(40, 45) is None


def test_fed_event_approaching_within_window():
    result = detect_fed_event_approaching(3, "FOMC decision")
    assert result["alert_type"] == "fed_event_approaching"


def test_fed_event_approaching_none_outside_window():
    assert detect_fed_event_approaching(30, "FOMC decision") is None
