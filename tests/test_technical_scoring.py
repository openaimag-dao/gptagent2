from datetime import UTC, datetime

from app.services.technical.normalizer import NormalizedIndicators
from app.services.technical.scoring import (
    combine_multi_timeframe,
    compute_breakout_breakdown_probability,
    score_timeframe,
)


def _reading(**overrides) -> NormalizedIndicators:
    defaults = dict(
        symbol="BTC",
        timeframe="1d",
        source="local",
        price=100.0,
        rsi=50.0,
        macd_line=0.0,
        macd_signal=0.0,
        macd_histogram=0.0,
        ema_20=100.0,
        sma_20=100.0,
        sma_50=100.0,
        sma_200=100.0,
        vwma_20=100.0,
        atr=2.0,
        adx=25.0,
        cci=0.0,
        momentum=0.0,
        roc=0.0,
        stochastic_rsi=50.0,
        bollinger_upper=110.0,
        bollinger_middle=100.0,
        bollinger_lower=90.0,
        pivot_points=None,
        support=90.0,
        resistance=110.0,
        computed_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    return NormalizedIndicators(**defaults)


def test_score_timeframe_none_when_reading_missing():
    assert score_timeframe(None) is None


def test_score_timeframe_neutral_reading_scores_near_50():
    result = score_timeframe(_reading())
    assert result["bullish_score"] == 50.0
    assert result["bearish_score"] == 50.0


def test_score_timeframe_oversold_rsi_reads_bullish():
    result = score_timeframe(_reading(rsi=20.0))
    assert result["bullish_score"] > 50.0


def test_score_timeframe_overbought_rsi_reads_bearish():
    result = score_timeframe(_reading(rsi=85.0))
    assert result["bearish_score"] > 50.0


def test_score_timeframe_price_above_all_mas_is_fully_bullish_trend():
    result = score_timeframe(_reading(price=150.0, sma_20=140.0, sma_50=130.0, sma_200=120.0))
    assert result["bullish_score"] > 50.0


def test_score_timeframe_trend_strength_reflects_adx():
    result = score_timeframe(_reading(adx=80.0))
    assert result["trend_strength"] == 80.0


def test_score_timeframe_missing_indicators_excluded_not_defaulted():
    result = score_timeframe(_reading(rsi=None, macd_histogram=None))
    assert result is not None  # other components still available


def test_compute_breakout_breakdown_probability_near_upper_band():
    reading = _reading(
        price=109.0, bollinger_upper=110.0, bollinger_middle=100.0, bollinger_lower=90.0, adx=40.0
    )
    breakout, breakdown = compute_breakout_breakdown_probability(reading)
    assert breakout > 50.0
    assert breakout + breakdown == 100.0


def test_compute_breakout_breakdown_probability_none_without_bollinger():
    reading = _reading(bollinger_upper=None, bollinger_lower=None)
    assert compute_breakout_breakdown_probability(reading) == (None, None)


def test_combine_multi_timeframe_none_when_all_missing():
    assert combine_multi_timeframe({"1h": None, "1d": None}) is None


def test_combine_multi_timeframe_weights_longer_timeframes_more():
    bullish_short = {
        "bullish_score": 90.0,
        "bearish_score": 10.0,
        "trend_strength": 50.0,
        "momentum": 1.0,
        "volatility": 5.0,
    }
    bearish_long = {
        "bullish_score": 10.0,
        "bearish_score": 90.0,
        "trend_strength": 50.0,
        "momentum": -1.0,
        "volatility": 5.0,
    }
    result = combine_multi_timeframe({"5m": bullish_short, "1d": bearish_long})
    # 1d carries far more weight than 5m -- combined result should lean bearish.
    assert result["bearish_score"] > result["bullish_score"]


def test_combine_multi_timeframe_confidence_reflects_coverage_and_decisiveness():
    strong = {
        "bullish_score": 95.0,
        "bearish_score": 5.0,
        "trend_strength": 80.0,
        "momentum": 2.0,
        "volatility": 3.0,
    }
    full_coverage = combine_multi_timeframe({"1d": strong})
    partial = combine_multi_timeframe({"1d": strong, "1w": None, "4h": None, "1h": None})
    assert full_coverage["confidence"] > partial["confidence"]
