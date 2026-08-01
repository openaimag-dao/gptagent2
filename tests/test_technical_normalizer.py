from types import SimpleNamespace

from app.services.technical.normalizer import normalize_local, normalize_tradingview


def _row(close, high=None, low=None, volume=100.0):
    return SimpleNamespace(
        close=close,
        high=high if high is not None else close + 1,
        low=low if low is not None else close - 1,
        volume=volume,
    )


def test_normalize_local_none_with_too_few_rows():
    rows = [_row(100.0), _row(101.0)]
    assert normalize_local("BTC", "1d", rows) is None


def test_normalize_local_produces_full_reading():
    rows = [_row(100.0 + i) for i in range(60)]
    result = normalize_local("BTC", "1d", rows)
    assert result is not None
    assert result.symbol == "BTC"
    assert result.timeframe == "1d"
    assert result.source == "local"
    assert result.price == rows[-1].close
    assert result.rsi is not None
    assert result.sma_20 is not None
    assert result.pivot_points is not None
    assert "pivot" in result.pivot_points


def test_normalize_local_none_volume_propagates_as_none_vwma():
    rows = [_row(100.0 + i, volume=None) for i in range(30)]
    result = normalize_local("BTC", "1d", rows)
    assert result.vwma_20 is None


def test_normalize_tradingview_none_when_no_price():
    assert normalize_tradingview("BTC", "1d", {}) is None
    assert normalize_tradingview("BTC", "1d", None) is None


def test_normalize_tradingview_maps_nested_fields():
    raw = {
        "price": 65000.0,
        "rsi": 42.5,
        "macd": {"macd": 1.2, "signal": 0.8, "histogram": 0.4},
        "ema20": 64000.0,
        "sma20": 63500.0,
        "bollinger": {"upper": 66000.0, "middle": 64500.0, "lower": 63000.0},
        "support": 62000.0,
        "resistance": 67000.0,
    }
    result = normalize_tradingview("BTC", "1h", raw)
    assert result.source == "tradingview"
    assert result.price == 65000.0
    assert result.rsi == 42.5
    assert result.macd_line == 1.2
    assert result.macd_signal == 0.8
    assert result.macd_histogram == 0.4
    assert result.ema_20 == 64000.0
    assert result.bollinger_upper == 66000.0
    assert result.support == 62000.0
    assert result.resistance == 67000.0
    # Fields TradingView didn't return stay honestly None, not backfilled.
    assert result.adx is None
    assert result.vwma_20 is None
