from app.services.breakout.detectors import (
    BREAKDOWN,
    BREAKOUT,
    FAILED_BREAKDOWN,
    FALSE_BREAKOUT,
    LIQUIDITY_SWEEP,
    RETEST,
    compute_rolling_vwap,
    compute_support_resistance,
    detect_breakout_event,
    score_breakout_event,
)

_LOOKBACK = 3
_RECENT_WINDOW = 2


def test_compute_support_resistance_excludes_last_candle():
    highs = [10.0, 11.0, 12.0, 9.0]
    lows = [9.0, 10.0, 11.0, 8.0]

    sr = compute_support_resistance(highs, lows, lookback=20)

    assert sr == {"prior_high": 12.0, "prior_low": 9.0}


def test_compute_support_resistance_none_when_too_short():
    assert compute_support_resistance([10.0], [9.0], lookback=20) is None


def test_compute_rolling_vwap_weights_by_volume():
    highs = [10.0, 12.0]
    lows = [8.0, 10.0]
    closes = [9.0, 11.0]
    volumes = [1.0, 3.0]

    vwap = compute_rolling_vwap(highs, lows, closes, volumes, window=2)

    tp1, tp2 = 9.0, 11.0
    expected = (tp1 * 1.0 + tp2 * 3.0) / 4.0
    assert vwap == expected


def test_compute_rolling_vwap_none_without_volume_data():
    assert compute_rolling_vwap([10.0], [9.0], [9.5], [None], window=5) is None


def test_detect_breakout_event_none_when_insufficient_history():
    assert detect_breakout_event([10.0, 11.0], [9.0, 9.5], [9.5, 10.0]) is None


def test_detect_breakout_event_bullish_breakout():
    highs = [10, 10, 10, 10, 10, 12]
    lows = [9, 9, 9, 9, 9, 11]
    closes = [9.5, 9.5, 9.5, 9.5, 9.5, 11.5]

    event = detect_breakout_event(
        highs, lows, closes, lookback=_LOOKBACK, recent_window=_RECENT_WINDOW
    )

    assert event == {"event_type": BREAKOUT, "direction": "bullish", "level": 10, "price": 11.5}


def test_detect_breakout_event_bearish_breakdown():
    highs = [10, 10, 10, 10, 10, 9]
    lows = [9, 9, 9, 9, 9, 7]
    closes = [9.5, 9.5, 9.5, 9.5, 9.5, 7.5]

    event = detect_breakout_event(
        highs, lows, closes, lookback=_LOOKBACK, recent_window=_RECENT_WINDOW
    )

    assert event == {"event_type": BREAKDOWN, "direction": "bearish", "level": 9, "price": 7.5}


def test_detect_breakout_event_false_breakout():
    highs = [10, 10, 10, 11.2, 10, 10.2]
    lows = [9, 9, 9, 9, 9, 9]
    closes = [9.5, 9.5, 9.5, 11, 9.5, 9.8]

    event = detect_breakout_event(
        highs, lows, closes, lookback=_LOOKBACK, recent_window=_RECENT_WINDOW
    )

    assert event == {
        "event_type": FALSE_BREAKOUT,
        "direction": "bearish",
        "level": 10,
        "price": 9.8,
    }


def test_detect_breakout_event_failed_breakdown():
    highs = [10, 10, 10, 9, 10, 9.5]
    lows = [9, 9, 9, 7.5, 9, 9]
    closes = [9.5, 9.5, 9.5, 8, 9.4, 9.2]

    event = detect_breakout_event(
        highs, lows, closes, lookback=_LOOKBACK, recent_window=_RECENT_WINDOW
    )

    assert event == {
        "event_type": FAILED_BREAKDOWN,
        "direction": "bullish",
        "level": 9,
        "price": 9.2,
    }


def test_detect_breakout_event_liquidity_sweep():
    highs = [10, 10, 10, 9.8, 9.8, 10.8]
    lows = [9, 9, 9, 9, 9, 9.4]
    closes = [9.5, 9.5, 9.5, 9.6, 9.7, 9.6]

    event = detect_breakout_event(
        highs, lows, closes, lookback=_LOOKBACK, recent_window=_RECENT_WINDOW
    )

    assert event == {
        "event_type": LIQUIDITY_SWEEP,
        "direction": "bearish",
        "level": 10,
        "price": 9.6,
    }


def test_detect_breakout_event_retest():
    highs = [10, 10, 10, 10.5, 10.2, 10.3]
    lows = [9, 9, 9, 9, 9, 9]
    closes = [9.5, 9.5, 9.5, 10.3, 9.8, 10.02]

    event = detect_breakout_event(
        highs, lows, closes, lookback=_LOOKBACK, recent_window=_RECENT_WINDOW
    )

    assert event == {"event_type": RETEST, "direction": "bullish", "level": 10, "price": 10.02}


def test_detect_breakout_event_none_when_nothing_happening():
    highs = [10, 10, 10, 10, 10, 10]
    lows = [9, 9, 9, 9, 9, 9]
    closes = [9.5, 9.5, 9.5, 9.5, 9.5, 9.5]

    event = detect_breakout_event(
        highs, lows, closes, lookback=_LOOKBACK, recent_window=_RECENT_WINDOW
    )

    assert event is None


def test_score_breakout_event_all_confirmed_gives_high_probability():
    confirmations = {
        "volume": True,
        "atr": True,
        "vwap": True,
        "regime": True,
        "oi_funding": True,
        "multi_timeframe": True,
    }

    result = score_breakout_event(
        BREAKOUT, "bullish", 11.5, 10.0, atr=1.0, confirmations=confirmations
    )

    assert result["probability_pct"] == 100.0
    assert result["confidence_pct"] == 100
    assert result["expected_continuation"] == "likely to continue"
    assert "Confirmed by" in result["reasoning"]


def test_score_breakout_event_excludes_unavailable_from_probability():
    confirmations = {
        "volume": True,
        "atr": None,
        "vwap": None,
        "regime": None,
        "oi_funding": None,
        "multi_timeframe": None,
    }

    result = score_breakout_event(
        BREAKOUT, "bullish", 11.5, 10.0, atr=None, confirmations=confirmations
    )

    assert result["probability_pct"] == 100.0
    assert result["confidence_pct"] == round(100 / 6)
    assert result["risk_score"] is None
    assert "No data for" in result["reasoning"]


def test_score_breakout_event_contradicted_lowers_probability():
    confirmations = {
        "volume": False,
        "atr": False,
        "vwap": False,
        "regime": False,
        "oi_funding": False,
        "multi_timeframe": False,
    }

    result = score_breakout_event(
        BREAKOUT, "bullish", 11.5, 10.0, atr=1.0, confirmations=confirmations
    )

    assert result["probability_pct"] == 0.0
    assert result["expected_continuation"] == "likely to fail/reverse"
    assert "Contradicted by" in result["reasoning"]


def test_score_breakout_event_risk_score_from_atr_distance():
    confirmations = {
        "volume": None,
        "atr": None,
        "vwap": None,
        "regime": None,
        "oi_funding": None,
        "multi_timeframe": None,
    }

    result = score_breakout_event(
        BREAKOUT, "bullish", price=11.0, level=10.0, atr=2.0, confirmations=confirmations
    )

    # distance_atr = 0.5 -> risk_score = 100 - 0.5*50 = 75
    assert result["risk_score"] == 75.0
