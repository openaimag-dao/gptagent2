"""Pure signal-event detection over NormalizedIndicators readings --
generates the exact event names the mission asks for. Cross-type events
(GoldenCross/DeathCross/MACD crossovers) need a previous reading to detect
the crossing; threshold events (RSIOverbought/RSIOversold/SupportBroken/
ResistanceBroken) only need the current one. detect_high_confidence_alignment
implements the mission's Smart Alerts example directly: RSI Oversold + MACD
Bullish Cross + Support Held -> HIGH_CONFIDENCE_BUY (bearish mirror for SELL).
"""

from app.services.technical.normalizer import NormalizedIndicators

RSI_OVERBOUGHT = 70.0
RSI_OVERSOLD = 30.0
_TREND_CHANGE_THRESHOLD = 10.0
_HIGH_CONFIDENCE_MIN_ALIGNED = 2


def detect_rsi_signals(reading: NormalizedIndicators | None) -> list[str]:
    if reading is None or reading.rsi is None:
        return []
    if reading.rsi >= RSI_OVERBOUGHT:
        return ["RSIOverbought"]
    if reading.rsi <= RSI_OVERSOLD:
        return ["RSIOversold"]
    return []


def detect_golden_death_cross(
    previous: NormalizedIndicators | None, current: NormalizedIndicators | None
) -> str | None:
    """SMA50 crossing SMA200."""
    if previous is None or current is None:
        return None
    if None in (previous.sma_50, previous.sma_200, current.sma_50, current.sma_200):
        return None
    if previous.sma_50 <= previous.sma_200 and current.sma_50 > current.sma_200:
        return "GoldenCross"
    if previous.sma_50 >= previous.sma_200 and current.sma_50 < current.sma_200:
        return "DeathCross"
    return None


def detect_macd_crossover(
    previous: NormalizedIndicators | None, current: NormalizedIndicators | None
) -> str | None:
    if previous is None or current is None:
        return None
    if None in (previous.macd_line, previous.macd_signal, current.macd_line, current.macd_signal):
        return None
    if previous.macd_line <= previous.macd_signal and current.macd_line > current.macd_signal:
        return "MACDBullishCrossover"
    if previous.macd_line >= previous.macd_signal and current.macd_line < current.macd_signal:
        return "MACDBearishCrossover"
    return None


def detect_support_resistance_events(current: NormalizedIndicators | None) -> list[str]:
    """Uses the CURRENT reading's own support/resistance -- computed from
    the trailing window up to and including this candle, so "broken" means
    price closed beyond the level that window otherwise implies."""
    if current is None or current.price is None:
        return []
    events = []
    if current.support is not None and current.price < current.support:
        events.append("SupportBroken")
    if current.resistance is not None and current.price > current.resistance:
        events.append("ResistanceBroken")
    return events


def detect_trend_change(
    previous_combined: dict | None, current_combined: dict | None
) -> str | None:
    """Compares two combined (multi-timeframe) technical-score readings."""
    if previous_combined is None or current_combined is None:
        return None
    prev_ts = previous_combined.get("trend_strength")
    curr_ts = current_combined.get("trend_strength")
    if prev_ts is None or curr_ts is None:
        return None
    delta = curr_ts - prev_ts
    if delta >= _TREND_CHANGE_THRESHOLD:
        return "TrendAcceleration"
    if delta <= -_TREND_CHANGE_THRESHOLD:
        return "TrendWeakening"
    return None


def detect_technical_bias(combined: dict | None, threshold: float = 20.0) -> str | None:
    if combined is None:
        return None
    bullish, bearish = combined.get("bullish_score"), combined.get("bearish_score")
    if bullish is None or bearish is None:
        return None
    if bullish - bearish >= threshold:
        return "TechnicalBullish"
    if bearish - bullish >= threshold:
        return "TechnicalBearish"
    return None


def detect_high_confidence_alignment(
    reading: NormalizedIndicators | None, macd_event: str | None, sr_events: list[str]
) -> dict | None:
    """Multiple independent technical signals pointing the same direction
    at once -- the mission's worked example (RSI Oversold + MACD Bullish
    Cross + Support Held). Requires at least 2 aligned reasons so a lone
    oscillator reading never fires this on its own."""
    if reading is None:
        return None

    bullish_reasons: list[str] = []
    bearish_reasons: list[str] = []

    if reading.rsi is not None:
        if reading.rsi <= RSI_OVERSOLD:
            bullish_reasons.append("RSI oversold")
        elif reading.rsi >= RSI_OVERBOUGHT:
            bearish_reasons.append("RSI overbought")

    if macd_event == "MACDBullishCrossover":
        bullish_reasons.append("MACD bullish crossover")
    elif macd_event == "MACDBearishCrossover":
        bearish_reasons.append("MACD bearish crossover")

    if "ResistanceBroken" in sr_events:
        bearish_reasons.append("resistance rejected")
    elif (
        "SupportBroken" not in sr_events
        and reading.support is not None
        and reading.price is not None
        and reading.price > reading.support
    ):
        bullish_reasons.append("support held")

    if len(bullish_reasons) >= _HIGH_CONFIDENCE_MIN_ALIGNED:
        return {"signal": "HIGH_CONFIDENCE_BUY", "reasons": bullish_reasons}
    if len(bearish_reasons) >= _HIGH_CONFIDENCE_MIN_ALIGNED:
        return {"signal": "HIGH_CONFIDENCE_SELL", "reasons": bearish_reasons}
    return None
