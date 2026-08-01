from app.services.alerts.detectors import (
    detect_correlation_break,
    detect_dxy_reversal,
    detect_etf_milestone,
    detect_fed_event_approaching,
    detect_flash_move,
    detect_funding_shift,
    detect_liquidity_change,
    detect_oi_spike,
    detect_regime_change,
    detect_technical_alignment,
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
    result = detect_whale_accumulation({"available": True, "classification": "long_heavy"})
    assert result["alert_type"] == "whale_positioning"


def test_whale_accumulation_none_when_balanced():
    assert detect_whale_accumulation({"available": True, "classification": "balanced"}) is None


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


def test_flash_move_fires_on_crash():
    result = detect_flash_move("BTC", -10.0)
    assert result["alert_type"] == "flash_crash"


def test_flash_move_fires_on_rally():
    result = detect_flash_move("BTC", 12.0)
    assert result["alert_type"] == "flash_rally"


def test_flash_move_none_below_threshold():
    assert detect_flash_move("BTC", 3.0) is None


def test_flash_move_none_without_data():
    assert detect_flash_move("BTC", None) is None


def test_funding_shift_fires_on_large_delta():
    result = detect_funding_shift(0.01, 0.10)
    assert result["alert_type"] == "funding_shift"
    assert "rising" in result["message"]


def test_funding_shift_none_on_small_delta():
    assert detect_funding_shift(0.01, 0.02) is None


def test_funding_shift_none_without_prior_reading():
    assert detect_funding_shift(None, 0.10) is None


def test_oi_spike_fires_on_large_delta():
    result = detect_oi_spike(5.0, 25.0)
    assert result["alert_type"] == "oi_spike"
    assert "building" in result["message"]


def test_oi_spike_none_on_small_delta():
    assert detect_oi_spike(5.0, 8.0) is None


def test_oi_spike_none_without_prior_reading():
    assert detect_oi_spike(None, 25.0) is None


def test_technical_alignment_none_without_alignment():
    assert detect_technical_alignment(None) is None


def test_technical_alignment_buy():
    alignment = {
        "signal": "HIGH_CONFIDENCE_BUY",
        "reasons": ["RSI oversold", "MACD bullish crossover"],
    }
    result = detect_technical_alignment(alignment, "BTC")
    assert result["alert_type"] == "high_confidence_buy"
    assert "HIGH CONFIDENCE BUY" in result["message"]
    assert result["confidence_pct"] == 80


def test_technical_alignment_sell():
    alignment = {
        "signal": "HIGH_CONFIDENCE_SELL",
        "reasons": ["RSI overbought", "resistance rejected"],
    }
    result = detect_technical_alignment(alignment, "ETH")
    assert result["alert_type"] == "high_confidence_sell"
    assert "HIGH CONFIDENCE SELL" in result["message"]
