from app.services.patterns.detectors import (
    detect_bearish_engulfing,
    detect_bullish_engulfing,
    detect_death_cross,
    detect_doji,
    detect_golden_cross,
    detect_hammer,
)


def test_detect_doji_flags_small_body_relative_to_range():
    opens = [100.0, 100.0]
    highs = [110.0, 110.0]
    lows = [90.0, 90.0]
    closes = [100.5, 108.0]  # tiny body vs range=20, then a large body

    result = detect_doji(opens, highs, lows, closes)

    assert result[0] is True
    assert result[1] is False


def test_detect_doji_zero_range_is_false():
    assert detect_doji([100.0], [100.0], [100.0], [100.0]) == [False]


def test_detect_hammer_long_lower_wick_small_upper_wick():
    # body = |102-100| = 2, lower wick = 100-90 = 10 (>=2x body), upper wick = 103-102 = 1 (<=body)
    opens = [100.0]
    highs = [103.0]
    lows = [90.0]
    closes = [102.0]

    assert detect_hammer(opens, highs, lows, closes) == [True]


def test_detect_hammer_rejects_large_upper_wick():
    # upper wick (10) exceeds body (2) -> not a hammer
    opens = [100.0]
    highs = [115.0]
    lows = [90.0]
    closes = [102.0]

    assert detect_hammer(opens, highs, lows, closes) == [False]


def test_detect_bullish_engulfing():
    # candle 0: bearish (open 110 -> close 100). candle 1: bullish, body engulfs candle 0's body.
    opens = [110.0, 95.0]
    closes = [100.0, 115.0]

    assert detect_bullish_engulfing(opens, closes) == [False, True]


def test_detect_bearish_engulfing():
    opens = [100.0, 115.0]
    closes = [110.0, 95.0]

    assert detect_bearish_engulfing(opens, closes) == [False, True]


def test_detect_bullish_engulfing_no_engulf_is_false():
    opens = [110.0, 108.0]
    closes = [100.0, 109.0]  # bullish but body doesn't engulf prior body

    assert detect_bullish_engulfing(opens, closes) == [False, False]


def test_detect_golden_cross():
    sma_short = [95.0, 105.0]
    sma_long = [100.0, 100.0]

    assert detect_golden_cross(sma_short, sma_long) == [False, True]


def test_detect_death_cross():
    sma_short = [105.0, 95.0]
    sma_long = [100.0, 100.0]

    assert detect_death_cross(sma_short, sma_long) == [False, True]


def test_crossover_handles_missing_data():
    sma_short = [None, 105.0]
    sma_long = [100.0, None]

    assert detect_golden_cross(sma_short, sma_long) == [False, False]
    assert detect_death_cross(sma_short, sma_long) == [False, False]
