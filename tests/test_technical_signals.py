from datetime import UTC, datetime

from app.services.technical.normalizer import NormalizedIndicators
from app.services.technical.signals import (
    detect_golden_death_cross,
    detect_high_confidence_alignment,
    detect_macd_crossover,
    detect_rsi_signals,
    detect_support_resistance_events,
    detect_technical_bias,
    detect_trend_change,
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


def test_detect_rsi_signals_overbought():
    assert detect_rsi_signals(_reading(rsi=75.0)) == ["RSIOverbought"]


def test_detect_rsi_signals_oversold():
    assert detect_rsi_signals(_reading(rsi=25.0)) == ["RSIOversold"]


def test_detect_rsi_signals_neutral_is_empty():
    assert detect_rsi_signals(_reading(rsi=50.0)) == []


def test_detect_rsi_signals_none_reading():
    assert detect_rsi_signals(None) == []


def test_detect_golden_cross():
    previous = _reading(sma_50=95.0, sma_200=100.0)
    current = _reading(sma_50=101.0, sma_200=100.0)
    assert detect_golden_death_cross(previous, current) == "GoldenCross"


def test_detect_death_cross():
    previous = _reading(sma_50=105.0, sma_200=100.0)
    current = _reading(sma_50=99.0, sma_200=100.0)
    assert detect_golden_death_cross(previous, current) == "DeathCross"


def test_detect_cross_none_without_previous():
    assert detect_golden_death_cross(None, _reading()) is None


def test_detect_macd_bullish_crossover():
    previous = _reading(macd_line=-1.0, macd_signal=0.0)
    current = _reading(macd_line=1.0, macd_signal=0.0)
    assert detect_macd_crossover(previous, current) == "MACDBullishCrossover"


def test_detect_macd_bearish_crossover():
    previous = _reading(macd_line=1.0, macd_signal=0.0)
    current = _reading(macd_line=-1.0, macd_signal=0.0)
    assert detect_macd_crossover(previous, current) == "MACDBearishCrossover"


def test_detect_support_broken():
    current = _reading(price=85.0, support=90.0)
    assert "SupportBroken" in detect_support_resistance_events(current)


def test_detect_resistance_broken():
    current = _reading(price=115.0, resistance=110.0)
    assert "ResistanceBroken" in detect_support_resistance_events(current)


def test_detect_no_sr_events_within_range():
    current = _reading(price=100.0, support=90.0, resistance=110.0)
    assert detect_support_resistance_events(current) == []


def test_detect_trend_change_acceleration():
    assert (
        detect_trend_change({"trend_strength": 20.0}, {"trend_strength": 35.0})
        == "TrendAcceleration"
    )


def test_detect_trend_change_weakening():
    assert (
        detect_trend_change({"trend_strength": 60.0}, {"trend_strength": 45.0}) == "TrendWeakening"
    )


def test_detect_trend_change_none_when_stable():
    assert detect_trend_change({"trend_strength": 50.0}, {"trend_strength": 52.0}) is None


def test_detect_technical_bias_bullish():
    assert (
        detect_technical_bias({"bullish_score": 80.0, "bearish_score": 20.0}) == "TechnicalBullish"
    )


def test_detect_technical_bias_bearish():
    assert (
        detect_technical_bias({"bullish_score": 20.0, "bearish_score": 80.0}) == "TechnicalBearish"
    )


def test_detect_technical_bias_none_when_close():
    assert detect_technical_bias({"bullish_score": 55.0, "bearish_score": 45.0}) is None


def test_high_confidence_buy_matches_mission_example():
    reading = _reading(rsi=25.0, price=100.0, support=90.0)
    result = detect_high_confidence_alignment(reading, "MACDBullishCrossover", [])
    assert result["signal"] == "HIGH_CONFIDENCE_BUY"
    assert "RSI oversold" in result["reasons"]
    assert "MACD bullish crossover" in result["reasons"]
    assert "support held" in result["reasons"]


def test_high_confidence_sell_matches_mission_example():
    reading = _reading(rsi=80.0, price=100.0, resistance=95.0)
    result = detect_high_confidence_alignment(reading, "MACDBearishCrossover", ["ResistanceBroken"])
    assert result["signal"] == "HIGH_CONFIDENCE_SELL"


def test_high_confidence_none_with_single_reason():
    reading = _reading(rsi=25.0, price=100.0, support=None)
    result = detect_high_confidence_alignment(reading, None, [])
    assert result is None
