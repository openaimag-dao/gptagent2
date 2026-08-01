"""AI Technical Score -- pure functions turning one timeframe's
NormalizedIndicators (and, for the combined view, several timeframes' worth)
into Bullish Score, Bearish Score, Trend Strength, Momentum, Volatility,
Breakout Probability, Breakdown Probability and Confidence. This is the
only thing this system exposes about a symbol's technicals -- raw
indicator values are never surfaced to a user (see
app.services.technical.engine); these functions are the "AI Brain must
interpret them" layer the mission requires.

Every component is bounded to roughly 0-100. Where the mapping is a
calibrated heuristic rather than a closed-form identity, it's documented
as such -- same convention as app.services.shocks.detectors.volatility_score.
"""

from app.services.common.scoring import clamp, weighted_average
from app.services.technical.normalizer import NormalizedIndicators

_SCORE_WEIGHTS: dict[str, float] = {
    "rsi": 15.0,
    "stochastic_rsi": 10.0,
    "trend_structure": 25.0,
    "macd": 20.0,
    "momentum": 10.0,
    "roc": 10.0,
    "cci": 10.0,
}

_TIMEFRAME_WEIGHTS: dict[str, float] = {
    "1m": 2.0,
    "5m": 3.0,
    "15m": 5.0,
    "30m": 5.0,
    "1h": 10.0,
    "4h": 20.0,
    "1d": 35.0,
    "1w": 20.0,
}


def _oscillator_bullish_bearish(value: float | None) -> tuple[float | None, float | None]:
    """0-100 oscillators (RSI, Stochastic RSI): low = oversold = bullish
    reversal signal, high = overbought = bearish signal."""
    if value is None:
        return None, None
    return clamp(100 - value), clamp(value)


def _trend_structure(reading: NormalizedIndicators) -> tuple[float | None, float | None]:
    """Bullish/bearish contribution from how many of the available moving
    averages price currently sits above vs. below."""
    if reading.price is None:
        return None, None
    mas = [m for m in (reading.sma_20, reading.sma_50, reading.sma_200) if m is not None]
    if not mas:
        return None, None
    # Price exactly at a moving average is neutral (half credit each way),
    # not "below" it.
    above = sum(1.0 if reading.price > m else 0.5 if reading.price == m else 0.0 for m in mas)
    return 100.0 * above / len(mas), 100.0 * (len(mas) - above) / len(mas)


def _macd_bullish_bearish(reading: NormalizedIndicators) -> tuple[float | None, float | None]:
    """MACD histogram sign/magnitude, normalized by ATR (a relative
    momentum-strength read) when available; sign-only otherwise."""
    if reading.macd_histogram is None:
        return None, None
    if reading.atr:
        bullish = clamp(50 + (reading.macd_histogram / reading.atr) * 50)
    else:
        bullish = 100.0 if reading.macd_histogram > 0 else 0.0
    return bullish, 100.0 - bullish


def _signed_pct_bullish_bearish(
    value_pct: float | None, scale: float = 5.0
) -> tuple[float | None, float | None]:
    if value_pct is None:
        return None, None
    bullish = clamp(50 + value_pct * scale)
    return bullish, 100.0 - bullish


def _cci_bullish_bearish(cci: float | None) -> tuple[float | None, float | None]:
    if cci is None:
        return None, None
    bullish = clamp(50 + cci / 4.0)
    return bullish, 100.0 - bullish


def score_timeframe(reading: NormalizedIndicators | None) -> dict | None:
    """Bullish/bearish/trend-strength/momentum/volatility for ONE timeframe."""
    if reading is None:
        return None

    rsi_bull, rsi_bear = _oscillator_bullish_bearish(reading.rsi)
    stoch_bull, stoch_bear = _oscillator_bullish_bearish(reading.stochastic_rsi)
    trend_bull, trend_bear = _trend_structure(reading)
    macd_bull, macd_bear = _macd_bullish_bearish(reading)

    momentum_pct = (
        reading.momentum / reading.price * 100
        if reading.momentum is not None and reading.price
        else None
    )
    momentum_bull, momentum_bear = _signed_pct_bullish_bearish(momentum_pct)
    roc_bull, roc_bear = _signed_pct_bullish_bearish(reading.roc)
    cci_bull, cci_bear = _cci_bullish_bearish(reading.cci)

    bullish_components = {
        "rsi": rsi_bull,
        "stochastic_rsi": stoch_bull,
        "trend_structure": trend_bull,
        "macd": macd_bull,
        "momentum": momentum_bull,
        "roc": roc_bull,
        "cci": cci_bull,
    }
    bearish_components = {
        "rsi": rsi_bear,
        "stochastic_rsi": stoch_bear,
        "trend_structure": trend_bear,
        "macd": macd_bear,
        "momentum": momentum_bear,
        "roc": roc_bear,
        "cci": cci_bear,
    }
    bullish_score = weighted_average(bullish_components, _SCORE_WEIGHTS)
    bearish_score = weighted_average(bearish_components, _SCORE_WEIGHTS)

    trend_strength = clamp(reading.adx) if reading.adx is not None else None
    volatility = (
        clamp(reading.atr / reading.price * 1000)
        if reading.atr is not None and reading.price
        else None
    )

    return {
        "timeframe": reading.timeframe,
        "bullish_score": round(bullish_score, 1) if bullish_score is not None else None,
        "bearish_score": round(bearish_score, 1) if bearish_score is not None else None,
        "trend_strength": round(trend_strength, 1) if trend_strength is not None else None,
        "momentum": round(momentum_pct, 2) if momentum_pct is not None else None,
        "volatility": round(volatility, 1) if volatility is not None else None,
    }


def compute_breakout_breakdown_probability(
    reading: NormalizedIndicators | None,
) -> tuple[float | None, float | None]:
    """Where price sits within its own Bollinger Band, blended with ADX
    trend confirmation -- higher near the upper band with a confirmed trend
    reads as breakout-likely, the mirror for breakdown. Complementary by
    construction (a simplification, documented as such): this reflects
    "which direction is more likely from here", not two independent odds."""
    if (
        reading is None
        or reading.price is None
        or reading.bollinger_upper is None
        or reading.bollinger_lower is None
    ):
        return None, None
    band_width = reading.bollinger_upper - reading.bollinger_lower
    if band_width <= 0:
        return None, None
    position = (reading.price - reading.bollinger_middle) / (band_width / 2)
    position_score = clamp(50 + position * 50)
    trend_confirmation = clamp(reading.adx) if reading.adx is not None else 50.0
    breakout = clamp((position_score + trend_confirmation) / 2)
    return round(breakout, 1), round(100.0 - breakout, 1)


def combine_multi_timeframe(per_timeframe_scores: dict[str, dict | None]) -> dict | None:
    """Weights longer timeframes more heavily (trend-following convention)
    and folds every available timeframe's score into one combined opinion,
    plus a Confidence read from how much timeframe coverage exists and how
    decisively bullish/bearish the combined read is (a 50/50 split reads
    low-confidence regardless of coverage)."""
    available = {label: s for label, s in per_timeframe_scores.items() if s is not None}
    if not available:
        return None

    weights = {label: _TIMEFRAME_WEIGHTS.get(label, 10.0) for label in available}
    bullish = weighted_average({k: v["bullish_score"] for k, v in available.items()}, weights)
    bearish = weighted_average({k: v["bearish_score"] for k, v in available.items()}, weights)
    trend_strength = weighted_average(
        {k: v["trend_strength"] for k, v in available.items()}, weights
    )
    momentum = weighted_average({k: v["momentum"] for k, v in available.items()}, weights)
    volatility = weighted_average({k: v["volatility"] for k, v in available.items()}, weights)

    coverage = 100.0 * len(available) / len(per_timeframe_scores)
    decisiveness = abs((bullish or 50.0) - (bearish or 50.0))
    confidence = clamp((coverage + decisiveness) / 2)

    return {
        "bullish_score": round(bullish, 1) if bullish is not None else None,
        "bearish_score": round(bearish, 1) if bearish is not None else None,
        "trend_strength": round(trend_strength, 1) if trend_strength is not None else None,
        "momentum": round(momentum, 2) if momentum is not None else None,
        "volatility": round(volatility, 1) if volatility is not None else None,
        "confidence": round(confidence, 1),
        "timeframes_covered": list(available.keys()),
        "timeframes_requested": list(per_timeframe_scores.keys()),
    }
