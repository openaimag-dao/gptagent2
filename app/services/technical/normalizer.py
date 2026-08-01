"""The "Normalizer" layer: TradingView MCP -> Adapter -> Normalizer ->
Provider Layer. Converts either raw TradingView MCP JSON or a series of
this project's own OHLCV rows into one common `NormalizedIndicators`
shape, so every downstream consumer (scoring, signals, the API/Telegram
surfaces) works identically regardless of which source answered -- "future
providers must follow the same interface" from the same normalized output,
not by branching on source elsewhere in the codebase.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from app.services.history.indicators import compute_atr, compute_macd, compute_rsi, compute_sma
from app.services.technical.indicators import (
    compute_adx,
    compute_bollinger_bands,
    compute_cci,
    compute_ema,
    compute_momentum,
    compute_pivot_points,
    compute_roc,
    compute_stochastic_rsi,
    compute_support_resistance,
    compute_vwma,
)

_MIN_ROWS_FOR_INDICATORS = 5


@dataclass
class NormalizedIndicators:
    symbol: str
    timeframe: str
    source: str  # "tradingview" | "local"
    price: float | None
    rsi: float | None
    macd_line: float | None
    macd_signal: float | None
    macd_histogram: float | None
    ema_20: float | None
    sma_20: float | None
    sma_50: float | None
    sma_200: float | None
    vwma_20: float | None
    atr: float | None
    adx: float | None
    cci: float | None
    momentum: float | None
    roc: float | None
    stochastic_rsi: float | None
    bollinger_upper: float | None
    bollinger_middle: float | None
    bollinger_lower: float | None
    pivot_points: dict[str, float] | None
    support: float | None
    resistance: float | None
    computed_at: datetime


def _last(values: list) -> float | None:
    return values[-1] if values else None


def normalize_local(symbol: str, timeframe: str, rows: list) -> NormalizedIndicators | None:
    """`rows` are ascending OHLCV rows (CryptoHistory/StockHistory/
    MacroHistory/ForexHistory) for one symbol/timeframe, as returned by
    app.services.history.repository.get_series(). Every indicator is
    computed fresh from the closing price series already stored -- no new
    data fetched. None if there isn't even enough history for the
    shortest-window indicator to produce one real value."""
    if len(rows) < _MIN_ROWS_FOR_INDICATORS:
        return None

    closes = [float(r.close) for r in rows]
    highs = [float(r.high) for r in rows]
    lows = [float(r.low) for r in rows]
    volumes = [float(r.volume) if r.volume is not None else None for r in rows]

    macd_line, macd_signal, macd_hist = compute_macd(closes)
    upper, middle, lower = compute_bollinger_bands(closes)
    support, resistance = compute_support_resistance(highs, lows)

    pivots = None
    if len(rows) >= 2:
        pivots = compute_pivot_points(highs[-2], lows[-2], closes[-2])

    return NormalizedIndicators(
        symbol=symbol,
        timeframe=timeframe,
        source="local",
        price=closes[-1],
        rsi=_last(compute_rsi(closes)),
        macd_line=_last(macd_line),
        macd_signal=_last(macd_signal),
        macd_histogram=_last(macd_hist),
        ema_20=_last(compute_ema(closes, 20)),
        sma_20=_last(compute_sma(closes, 20)),
        sma_50=_last(compute_sma(closes, 50)),
        sma_200=_last(compute_sma(closes, 200)),
        vwma_20=_last(compute_vwma(closes, volumes, 20)),
        atr=_last(compute_atr(highs, lows, closes)),
        adx=_last(compute_adx(highs, lows, closes)),
        cci=_last(compute_cci(highs, lows, closes)),
        momentum=_last(compute_momentum(closes)),
        roc=_last(compute_roc(closes)),
        stochastic_rsi=_last(compute_stochastic_rsi(closes)),
        bollinger_upper=_last(upper),
        bollinger_middle=_last(middle),
        bollinger_lower=_last(lower),
        pivot_points=pivots,
        support=support,
        resistance=resistance,
        computed_at=datetime.now(UTC),
    )


def normalize_tradingview(symbol: str, timeframe: str, raw: dict) -> NormalizedIndicators | None:
    """Maps a TradingView MCP response onto the same shape `normalize_local`
    produces. Documented request contract (see tradingview_client.py):
    `{"price": float, "rsi": float, "macd": {"macd": float, "signal": float,
    "histogram": float}, "ema20": float, "sma20"/"sma50"/"sma200": float,
    "vwma20": float, "atr": float, "adx": float, "cci": float,
    "momentum": float, "roc": float, "stoch_rsi": float, "bollinger":
    {"upper": float, "middle": float, "lower": float}, "pivot_points": {...},
    "support": float, "resistance": float}`. Any field TradingView omits is
    honestly `None`, never backfilled from local computation -- mixing
    sources within one reading would misattribute provenance."""
    if not raw or "price" not in raw:
        return None

    macd = raw.get("macd") or {}
    bollinger = raw.get("bollinger") or {}
    return NormalizedIndicators(
        symbol=symbol,
        timeframe=timeframe,
        source="tradingview",
        price=raw.get("price"),
        rsi=raw.get("rsi"),
        macd_line=macd.get("macd"),
        macd_signal=macd.get("signal"),
        macd_histogram=macd.get("histogram"),
        ema_20=raw.get("ema20"),
        sma_20=raw.get("sma20"),
        sma_50=raw.get("sma50"),
        sma_200=raw.get("sma200"),
        vwma_20=raw.get("vwma20"),
        atr=raw.get("atr"),
        adx=raw.get("adx"),
        cci=raw.get("cci"),
        momentum=raw.get("momentum"),
        roc=raw.get("roc"),
        stochastic_rsi=raw.get("stoch_rsi"),
        bollinger_upper=bollinger.get("upper"),
        bollinger_middle=bollinger.get("middle"),
        bollinger_lower=bollinger.get("lower"),
        pivot_points=raw.get("pivot_points"),
        support=raw.get("support"),
        resistance=raw.get("resistance"),
        computed_at=datetime.now(UTC),
    )
