"""Pure technical-indicator math not already covered by
app.services.history.indicators (RSI/MACD/SMA/ATR/returns/volatility/
volume-change) -- same conventions: ordered OHLCV series oldest-first, no
I/O, unit-testable, `None` rather than a fabricated number wherever there
isn't enough history yet.

Deliberately NOT implemented, and honestly reported unavailable by
app.services.technical.provider rather than approximated: Ichimoku Cloud
and Parabolic SAR (both meaningfully more complex stateful/multi-line
algorithms than the rest of this module, low value-to-complexity ratio
for a first pass), SuperTrend (same reasoning -- an ATR-banded trend-flip
state machine), and Volume Profile (needs intraday volume-at-price
granularity; this project only has aggregate per-candle volume, exactly
the "if available" carve-out the spec itself allows).
"""

import numpy as np

from app.services.history.indicators import _ema, compute_rsi, compute_sma

__all__ = [
    "compute_bollinger_bands",
    "compute_cci",
    "compute_ema",
    "compute_momentum",
    "compute_pivot_points",
    "compute_roc",
    "compute_stochastic_rsi",
    "compute_support_resistance",
    "compute_vwma",
    "compute_adx",
]


def compute_ema(closes: list[float], span: int) -> list[float | None]:
    if len(closes) < span:
        return [None] * len(closes)
    return [None] * (span - 1) + _ema(closes, span)[span - 1 :]


def compute_bollinger_bands(
    closes: list[float], window: int = 20, num_std: float = 2.0
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Returns (upper, middle, lower) bands. `middle` is the plain SMA."""
    middle = compute_sma(closes, window)
    upper: list[float | None] = []
    lower: list[float | None] = []
    for i in range(len(closes)):
        if i + 1 < window or middle[i] is None:
            upper.append(None)
            lower.append(None)
            continue
        window_values = closes[i + 1 - window : i + 1]
        stdev = float(np.std(window_values, ddof=0))
        upper.append(middle[i] + num_std * stdev)
        lower.append(middle[i] - num_std * stdev)
    return upper, middle, lower


def compute_vwma(
    closes: list[float], volumes: list[float | None], window: int = 20
) -> list[float | None]:
    """Volume-weighted moving average; `None` for any window containing a
    missing volume reading rather than silently dropping it from the average."""
    result: list[float | None] = []
    for i in range(len(closes)):
        if i + 1 < window:
            result.append(None)
            continue
        price_slice = closes[i + 1 - window : i + 1]
        volume_slice = volumes[i + 1 - window : i + 1]
        if any(v is None for v in volume_slice):
            result.append(None)
            continue
        total_volume = sum(volume_slice)
        result.append(
            sum(p * v for p, v in zip(price_slice, volume_slice, strict=True)) / total_volume
            if total_volume
            else None
        )
    return result


def compute_stochastic_rsi(
    closes: list[float], rsi_window: int = 14, stoch_window: int = 14
) -> list[float | None]:
    """0-100 scale: where the current RSI sits within its own trailing range."""
    rsi = compute_rsi(closes, rsi_window)
    result: list[float | None] = []
    for i in range(len(rsi)):
        window_values = [r for r in rsi[max(0, i - stoch_window + 1) : i + 1] if r is not None]
        if rsi[i] is None or len(window_values) < stoch_window:
            result.append(None)
            continue
        lo, hi = min(window_values), max(window_values)
        result.append(100.0 * (rsi[i] - lo) / (hi - lo) if hi > lo else 50.0)
    return result


def compute_roc(closes: list[float], window: int = 12) -> list[float | None]:
    result: list[float | None] = []
    for i in range(len(closes)):
        if i < window or closes[i - window] == 0:
            result.append(None)
        else:
            result.append((closes[i] - closes[i - window]) / closes[i - window] * 100.0)
    return result


def compute_momentum(closes: list[float], window: int = 10) -> list[float | None]:
    result: list[float | None] = []
    for i in range(len(closes)):
        result.append(closes[i] - closes[i - window] if i >= window else None)
    return result


def compute_cci(
    highs: list[float], lows: list[float], closes: list[float], window: int = 20
) -> list[float | None]:
    typical_prices = [
        (high + low + close) / 3 for high, low, close in zip(highs, lows, closes, strict=True)
    ]
    result: list[float | None] = []
    for i in range(len(typical_prices)):
        if i + 1 < window:
            result.append(None)
            continue
        window_values = typical_prices[i + 1 - window : i + 1]
        mean = sum(window_values) / window
        mean_deviation = sum(abs(v - mean) for v in window_values) / window
        result.append(
            (typical_prices[i] - mean) / (0.015 * mean_deviation) if mean_deviation else None
        )
    return result


def compute_adx(
    highs: list[float], lows: list[float], closes: list[float], window: int = 14
) -> list[float | None]:
    """Wilder's ADX. First value appears at index `2 * window - 1`
    (window periods to seed +DI/-DI, another window to seed the DX average)."""
    n = len(closes)
    result: list[float | None] = [None] * n
    if n <= 2 * window:
        return result

    plus_dm = [0.0]
    minus_dm = [0.0]
    true_ranges = [highs[0] - lows[0]]
    for i in range(1, n):
        up_move = highs[i] - highs[i - 1]
        down_move = lows[i - 1] - lows[i]
        plus_dm.append(up_move if up_move > down_move and up_move > 0 else 0.0)
        minus_dm.append(down_move if down_move > up_move and down_move > 0 else 0.0)
        true_ranges.append(
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
        )

    def _wilder_smooth(values: list[float]) -> list[float]:
        smoothed = [sum(values[1 : window + 1])]
        for v in values[window + 1 :]:
            smoothed.append(smoothed[-1] - smoothed[-1] / window + v)
        return smoothed

    smoothed_tr = _wilder_smooth(true_ranges)
    smoothed_plus_dm = _wilder_smooth(plus_dm)
    smoothed_minus_dm = _wilder_smooth(minus_dm)

    dx_values: list[float] = []
    for tr, pdm, mdm in zip(smoothed_tr, smoothed_plus_dm, smoothed_minus_dm, strict=True):
        if tr == 0:
            dx_values.append(0.0)
            continue
        plus_di = 100 * pdm / tr
        minus_di = 100 * mdm / tr
        di_sum = plus_di + minus_di
        dx_values.append(100 * abs(plus_di - minus_di) / di_sum if di_sum else 0.0)

    adx = sum(dx_values[:window]) / window
    result[2 * window - 1] = adx
    for i, dx in enumerate(dx_values[window:], start=2 * window):
        if i >= n:
            break
        adx = (adx * (window - 1) + dx) / window
        result[i] = adx

    return result


def compute_pivot_points(
    prior_high: float, prior_low: float, prior_close: float
) -> dict[str, float]:
    """Classic/standard floor-trader pivots from the most recently completed
    candle -- support/resistance levels for the candle now forming."""
    pivot = (prior_high + prior_low + prior_close) / 3
    return {
        "pivot": pivot,
        "r1": 2 * pivot - prior_low,
        "s1": 2 * pivot - prior_high,
        "r2": pivot + (prior_high - prior_low),
        "s2": pivot - (prior_high - prior_low),
        "r3": prior_high + 2 * (pivot - prior_low),
        "s3": prior_low - 2 * (prior_high - pivot),
    }


def compute_support_resistance(
    highs: list[float], lows: list[float], window: int = 20
) -> tuple[float | None, float | None]:
    """Swing-based support/resistance: the trailing window's low/high --
    simple and honestly labeled as such, not a fabricated claim of
    pattern-recognized structural levels."""
    if len(highs) < window:
        return None, None
    return min(lows[-window:]), max(highs[-window:])
