from datetime import UTC, datetime, timedelta

from app.services.history.resample import resample_candles
from app.services.history.schemas import Candle, Timeframe


def _hourly_candle(hour: int, price: float) -> Candle:
    return Candle(
        symbol="BTC",
        timeframe=Timeframe.ONE_HOUR,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=hour),
        open=price,
        high=price + 1,
        low=price - 1,
        close=price,
        volume=10.0,
        source="test",
    )


def test_resample_empty_list_is_empty():
    assert resample_candles([], Timeframe.FOUR_HOUR) == []


def test_resample_hourly_to_four_hour_aggregates_ohlcv():
    candles = [_hourly_candle(h, 100.0 + h) for h in range(4)]  # hours 0,1,2,3 -> one 4h bucket

    resampled = resample_candles(candles, Timeframe.FOUR_HOUR)

    assert len(resampled) == 1
    bar = resampled[0]
    assert bar.timeframe == Timeframe.FOUR_HOUR
    assert bar.open == candles[0].open
    assert bar.close == candles[-1].close
    assert bar.high == max(c.high for c in candles)
    assert bar.low == min(c.low for c in candles)
    assert bar.volume == sum(c.volume for c in candles)


def test_resample_produces_one_bucket_per_four_hours():
    candles = [_hourly_candle(h, 100.0 + h) for h in range(8)]  # two full 4h buckets

    resampled = resample_candles(candles, Timeframe.FOUR_HOUR)

    assert len(resampled) == 2
    assert resampled[0].timestamp == datetime(2026, 1, 1, 0, tzinfo=UTC)
    assert resampled[1].timestamp == datetime(2026, 1, 1, 4, tzinfo=UTC)


def _five_min_candle(minute_offset: int, price: float, volume: float | None) -> Candle:
    return Candle(
        symbol="BTC",
        timeframe=Timeframe.FIVE_MINUTE,
        timestamp=datetime(2026, 1, 1, 10, 0, tzinfo=UTC) + timedelta(minutes=minute_offset),
        open=price,
        high=price + 1,
        low=price - 1,
        close=price,
        volume=volume,
        source="realtime_coinbase_1m_sampled",
    )


def test_resample_five_minute_to_fifteen_minute_aggregates_ohlc():
    candles = [_five_min_candle(m, 100.0 + m, volume=10.0) for m in (0, 5, 10)]

    resampled = resample_candles(candles, Timeframe.FIFTEEN_MINUTE)

    assert len(resampled) == 1
    bar = resampled[0]
    assert bar.timeframe == Timeframe.FIFTEEN_MINUTE
    assert bar.timestamp == datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
    assert bar.open == candles[0].open
    assert bar.close == candles[-1].close
    assert bar.high == max(c.high for c in candles)
    assert bar.low == min(c.low for c in candles)
    assert bar.volume == 30.0


def test_resample_five_minute_to_fifteen_minute_keeps_volume_none_when_all_inputs_lack_it():
    # Realtime-aggregated 5m candles never carry volume (no per-trade size
    # in the tick feed, see aggregator.py) -- pandas' default sum() of an
    # all-NaN group is 0.0, which would silently turn "we don't have this
    # data" into a fabricated "confirmed zero volume" claim.
    candles = [_five_min_candle(m, 100.0 + m, volume=None) for m in (0, 5, 10)]

    resampled = resample_candles(candles, Timeframe.FIFTEEN_MINUTE)

    assert len(resampled) == 1
    assert resampled[0].volume is None
