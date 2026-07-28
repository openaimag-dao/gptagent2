"""Breakout Intelligence -- pure detection/scoring functions over OHLCV
series. No I/O: BreakoutEngine supplies the actual candle/ATR/regime/
feature reads and persists the result.

Detection classifies the most recent candle against a swing high/low
computed from history that excludes both the last candle and the
`recent_window` candles right before it (so a recent close genuinely can
sit on either side of the level, rather than the level being redefined by
the very candle being tested). One of six mutually exclusive outcomes can
result: a liquidity sweep (a wick punches through the level but the candle
closes back inside, rejecting), a false breakout / failed breakdown (a
recent close beyond the level has since closed back on the wrong side), a
retest (a recent close broke the level and the last candle sits within a
small tolerance of it, still on the breakout side), or a fresh
breakout/breakdown. None means nothing currently applies.

Scoring turns six independent confirmation checks (volume, ATR-relative
move size, rolling VWAP, market regime, OI/funding momentum, and
confirmation on a finer timeframe) into a probability via
`weighted_average` -- any check the platform has no data for is honestly
excluded rather than counted as a strike against the signal.
"""

from app.services.common.scoring import clamp, weighted_average

DEFAULT_LOOKBACK = 20
DEFAULT_RECENT_WINDOW = 5

BREAKOUT = "breakout"
BREAKDOWN = "breakdown"
FALSE_BREAKOUT = "false_breakout"
FAILED_BREAKDOWN = "failed_breakdown"
RETEST = "retest"
LIQUIDITY_SWEEP = "liquidity_sweep"

_BULLISH = "bullish"
_BEARISH = "bearish"

_CONFIRMATION_WEIGHTS: dict[str, float] = {
    "volume": 20.0,
    "atr": 15.0,
    "vwap": 15.0,
    "regime": 20.0,
    "oi_funding": 15.0,
    "multi_timeframe": 15.0,
}

_FACTOR_LABELS: dict[str, str] = {
    "volume": "volume",
    "atr": "ATR-relative move size",
    "vwap": "VWAP position",
    "regime": "market regime",
    "oi_funding": "OI/funding momentum",
    "multi_timeframe": "finer-timeframe confirmation",
}

_EXPECTED_CONTINUATION_LABELS: tuple[tuple[float, str], ...] = (
    (70.0, "likely to continue"),
    (55.0, "leaning continuation"),
    (45.0, "uncertain"),
    (30.0, "leaning reversal"),
)


def compute_support_resistance(
    highs: list[float],
    lows: list[float],
    lookback: int = DEFAULT_LOOKBACK,
    exclude_recent: int = 0,
) -> dict | None:
    """Prior swing high/low over the trailing `lookback` candles, excluding
    the most recent `exclude_recent + 1` candles -- `exclude_recent=0`
    excludes just the still-forming last candle."""
    trim = exclude_recent + 1
    if len(highs) <= trim or len(lows) <= trim:
        return None
    level_highs = highs[:-trim][-lookback:]
    level_lows = lows[:-trim][-lookback:]
    if not level_highs or not level_lows:
        return None
    return {"prior_high": max(level_highs), "prior_low": min(level_lows)}


def compute_rolling_vwap(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    volumes: list[float | None],
    window: int = DEFAULT_LOOKBACK,
) -> float | None:
    """Volume-weighted average typical price over the trailing `window`
    candles -- a rolling proxy for session VWAP, since this project only
    stores daily/4h/1h OHLCV bars, not intraday tick volume. Honestly None
    when no candle in the window has volume data."""
    n = len(closes)
    start = max(0, n - window)
    tp_vol_sum = 0.0
    vol_sum = 0.0
    for i in range(start, n):
        volume = volumes[i] if i < len(volumes) else None
        if volume is None or volume <= 0:
            continue
        typical_price = (highs[i] + lows[i] + closes[i]) / 3
        tp_vol_sum += typical_price * volume
        vol_sum += volume
    return tp_vol_sum / vol_sum if vol_sum > 0 else None


def _event(event_type: str, direction: str, level: float, price: float) -> dict:
    return {"event_type": event_type, "direction": direction, "level": level, "price": price}


def detect_breakout_event(
    highs: list[float],
    lows: list[float],
    closes: list[float],
    lookback: int = DEFAULT_LOOKBACK,
    recent_window: int = DEFAULT_RECENT_WINDOW,
) -> dict | None:
    """Returns {"event_type", "direction", "level", "price"} for whichever
    single condition currently applies to the last candle, or None."""
    n = len(closes)
    if n < lookback + recent_window + 1:
        return None

    sr = compute_support_resistance(highs, lows, lookback, exclude_recent=recent_window)
    if sr is None:
        return None
    prior_high, prior_low = sr["prior_high"], sr["prior_low"]

    trim = recent_window + 1
    recent_closes = closes[-trim:-1]
    last_high, last_low, last_close = highs[-1], lows[-1], closes[-1]
    midpoint = (last_high + last_low) / 2
    tolerance = max(prior_high - prior_low, 1e-9) * 0.05

    if last_high > prior_high and last_close <= prior_high and last_close < midpoint:
        return _event(LIQUIDITY_SWEEP, _BEARISH, prior_high, last_close)
    if last_low < prior_low and last_close >= prior_low and last_close > midpoint:
        return _event(LIQUIDITY_SWEEP, _BULLISH, prior_low, last_close)

    broke_high_recently = any(c > prior_high for c in recent_closes)
    broke_low_recently = any(c < prior_low for c in recent_closes)

    if broke_high_recently and last_close <= prior_high:
        return _event(FALSE_BREAKOUT, _BEARISH, prior_high, last_close)
    if broke_low_recently and last_close >= prior_low:
        return _event(FAILED_BREAKDOWN, _BULLISH, prior_low, last_close)

    if (
        broke_high_recently
        and last_close > prior_high
        and abs(last_close - prior_high) <= tolerance
    ):
        return _event(RETEST, _BULLISH, prior_high, last_close)
    if broke_low_recently and last_close < prior_low and abs(last_close - prior_low) <= tolerance:
        return _event(RETEST, _BEARISH, prior_low, last_close)

    if last_close > prior_high:
        return _event(BREAKOUT, _BULLISH, prior_high, last_close)
    if last_close < prior_low:
        return _event(BREAKDOWN, _BEARISH, prior_low, last_close)

    return None


def _expected_continuation_label(probability_pct: float | None) -> str:
    if probability_pct is None:
        return "unknown -- insufficient confirmation data"
    for threshold, label in _EXPECTED_CONTINUATION_LABELS:
        if probability_pct >= threshold:
            return label
    return "likely to fail/reverse"


def _reasoning(event_type: str, direction: str, confirmations: dict[str, bool | None]) -> str:
    confirmed = [_FACTOR_LABELS[k] for k, v in confirmations.items() if v is True]
    contradicted = [_FACTOR_LABELS[k] for k, v in confirmations.items() if v is False]
    unavailable = [_FACTOR_LABELS[k] for k, v in confirmations.items() if v is None]
    parts = [f"{event_type.replace('_', ' ').title()} ({direction})."]
    if confirmed:
        parts.append(f"Confirmed by: {', '.join(confirmed)}.")
    if contradicted:
        parts.append(f"Contradicted by: {', '.join(contradicted)}.")
    if unavailable:
        parts.append(f"No data for: {', '.join(unavailable)}.")
    return " ".join(parts)


def score_breakout_event(
    event_type: str,
    direction: str,
    price: float,
    level: float,
    atr: float | None,
    confirmations: dict[str, bool | None],
) -> dict:
    """Turns the six confirmation checks into a probability/confidence/risk
    read plus a human-readable reasoning string. Missing confirmations are
    excluded from the weighted average rather than counted against it;
    confidence_pct instead measures what fraction of the six checks were
    actually possible to run."""
    scored = {
        name: (100.0 if value else 0.0) if value is not None else None
        for name, value in confirmations.items()
    }
    probability_pct = weighted_average(scored, _CONFIRMATION_WEIGHTS)
    available = [v for v in confirmations.values() if v is not None]
    confidence_pct = round(100 * len(available) / len(confirmations)) if confirmations else 0

    risk_score = None
    if atr is not None and atr > 0:
        distance_atr = abs(price - level) / atr
        risk_score = clamp(100 - distance_atr * 50)

    return {
        "probability_pct": round(probability_pct, 1) if probability_pct is not None else None,
        "confidence_pct": confidence_pct,
        "risk_score": round(risk_score, 1) if risk_score is not None else None,
        "expected_continuation": _expected_continuation_label(probability_pct),
        "reasoning": _reasoning(event_type, direction, confirmations),
    }
