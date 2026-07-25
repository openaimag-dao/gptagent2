"""Pure, deterministic technical pattern detectors over OHLCV + moving-average series.

Every function returns a list of booleans aligned index-for-index with its
input -- no I/O, no fabricated signals, just well-known rule-based
definitions applied to already-computed data.
"""

_DOJI_BODY_RATIO = 0.1
_HAMMER_WICK_RATIO = 2.0


def detect_doji(
    opens: list[float], highs: list[float], lows: list[float], closes: list[float]
) -> list[bool]:
    """Body is a small fraction of the candle's total range -- indecision."""
    result = []
    for o, h, low, c in zip(opens, highs, lows, closes):
        candle_range = h - low
        result.append(candle_range > 0 and abs(c - o) <= _DOJI_BODY_RATIO * candle_range)
    return result


def detect_hammer(
    opens: list[float], highs: list[float], lows: list[float], closes: list[float]
) -> list[bool]:
    """Small body near the top of the range with a long lower wick -- bullish reversal."""
    result = []
    for o, h, low, c in zip(opens, highs, lows, closes):
        body = abs(c - o)
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - low
        result.append(body > 0 and lower_wick >= _HAMMER_WICK_RATIO * body and upper_wick <= body)
    return result


def detect_bullish_engulfing(opens: list[float], closes: list[float]) -> list[bool]:
    """Current bullish candle's body fully engulfs the prior bearish candle's body."""
    result = [False]
    for i in range(1, len(opens)):
        prev_bearish = closes[i - 1] < opens[i - 1]
        curr_bullish = closes[i] > opens[i]
        engulfs = opens[i] <= closes[i - 1] and closes[i] >= opens[i - 1]
        result.append(prev_bearish and curr_bullish and engulfs)
    return result


def detect_bearish_engulfing(opens: list[float], closes: list[float]) -> list[bool]:
    """Current bearish candle's body fully engulfs the prior bullish candle's body."""
    result = [False]
    for i in range(1, len(opens)):
        prev_bullish = closes[i - 1] > opens[i - 1]
        curr_bearish = closes[i] < opens[i]
        engulfs = opens[i] >= closes[i - 1] and closes[i] <= opens[i - 1]
        result.append(prev_bullish and curr_bearish and engulfs)
    return result


def detect_golden_cross(sma_short: list[float | None], sma_long: list[float | None]) -> list[bool]:
    """SMA 50 crosses above SMA 200 -- classic bullish trend-change signal."""
    return _detect_crossover(sma_short, sma_long, above=True)


def detect_death_cross(sma_short: list[float | None], sma_long: list[float | None]) -> list[bool]:
    """SMA 50 crosses below SMA 200 -- classic bearish trend-change signal."""
    return _detect_crossover(sma_short, sma_long, above=False)


def _detect_crossover(
    short: list[float | None], long: list[float | None], above: bool
) -> list[bool]:
    result = [False]
    for i in range(1, len(short)):
        prev_short, prev_long = short[i - 1], long[i - 1]
        curr_short, curr_long = short[i], long[i]
        if None in (prev_short, prev_long, curr_short, curr_long):
            result.append(False)
            continue
        if above:
            result.append(prev_short <= prev_long and curr_short > curr_long)
        else:
            result.append(prev_short >= prev_long and curr_short < curr_long)
    return result
