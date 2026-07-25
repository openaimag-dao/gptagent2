"""Pure technical-indicator math over ordered OHLCV series -- no I/O, unit-testable.

Every function takes/returns lists aligned index-for-index with the input
series (oldest first); positions without enough history to compute a value
yield None rather than a fabricated number.
"""

import numpy as np


def compute_returns(closes: list[float]) -> list[float | None]:
    returns: list[float | None] = [None]
    for prev, curr in zip(closes, closes[1:]):
        returns.append((curr - prev) / prev if prev else None)
    return returns


def compute_volatility(returns: list[float | None], window: int = 14) -> list[float | None]:
    """Rolling sample stddev of returns over `window` periods."""
    result: list[float | None] = []
    for i in range(len(returns)):
        window_values = [r for r in returns[max(0, i - window + 1) : i + 1] if r is not None]
        result.append(float(np.std(window_values, ddof=1)) if len(window_values) >= 2 else None)
    return result


def compute_volume_change(volumes: list[float | None]) -> list[float | None]:
    result: list[float | None] = [None]
    for prev, curr in zip(volumes, volumes[1:]):
        if prev is None or curr is None or prev == 0:
            result.append(None)
        else:
            result.append((curr - prev) / prev)
    return result


def compute_sma(closes: list[float], window: int) -> list[float | None]:
    result: list[float | None] = []
    for i in range(len(closes)):
        if i + 1 < window:
            result.append(None)
        else:
            result.append(float(np.mean(closes[i + 1 - window : i + 1])))
    return result


def compute_moving_averages(
    closes: list[float], windows: tuple[int, ...] = (20, 50, 200)
) -> dict[int, list[float | None]]:
    return {window: compute_sma(closes, window) for window in windows}


def _ema(values: list[float], span: int) -> list[float]:
    alpha = 2 / (span + 1)
    ema: list[float] = []
    for i, value in enumerate(values):
        ema.append(value if i == 0 else alpha * value + (1 - alpha) * ema[-1])
    return ema


def compute_macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float | None], list[float | None], list[float | None]]:
    """Standard EMA-based MACD. Line/signal/histogram are None before `slow`
    closes have accumulated; like any EMA they converge rather than requiring
    a hard window after that point."""
    n = len(closes)
    if n < slow:
        none_list: list[float | None] = [None] * n
        return none_list, none_list, none_list

    fast_ema = _ema(closes, fast)
    slow_ema = _ema(closes, slow)
    macd_line = [f - s for f, s in zip(fast_ema, slow_ema)]

    signal_seed = _ema(macd_line[slow - 1 :], signal)
    signal_line: list[float | None] = [None] * (slow - 1) + signal_seed
    macd_line_out: list[float | None] = [None] * (slow - 1) + macd_line[slow - 1 :]
    histogram = [
        (m - s) if (m is not None and s is not None) else None
        for m, s in zip(macd_line_out, signal_line)
    ]
    return macd_line_out, signal_line, histogram


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def compute_rsi(closes: list[float], window: int = 14) -> list[float | None]:
    """Wilder's RSI. First value appears at index `window`."""
    n = len(closes)
    result: list[float | None] = [None] * n
    if n <= window:
        return result

    deltas = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains = [max(d, 0.0) for d in deltas]
    losses = [max(-d, 0.0) for d in deltas]

    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    result[window] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(window, len(deltas)):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window
        result[i + 1] = _rsi_from_averages(avg_gain, avg_loss)

    return result


def compute_atr(
    highs: list[float], lows: list[float], closes: list[float], window: int = 14
) -> list[float | None]:
    """Wilder's Average True Range. First value appears at index `window`."""
    n = len(closes)
    result: list[float | None] = [None] * n
    if n <= window:
        return result

    true_ranges = [highs[0] - lows[0]]
    for i in range(1, n):
        true_ranges.append(
            max(
                highs[i] - lows[i],
                abs(highs[i] - closes[i - 1]),
                abs(lows[i] - closes[i - 1]),
            )
        )

    atr = sum(true_ranges[1 : window + 1]) / window
    result[window] = atr
    for i in range(window + 1, n):
        atr = (atr * (window - 1) + true_ranges[i]) / window
        result[i] = atr

    return result
