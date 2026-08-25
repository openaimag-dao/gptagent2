import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.realtime import aggregator
from app.services.realtime.aggregator import BucketState, bucket_start
from app.services.realtime.schemas import RealtimePriceTick


def _tick(symbol="BTC", price=100.0, event_timestamp=None):
    ts = event_timestamp or datetime.now(UTC)
    return RealtimePriceTick(symbol=symbol, price=price, event_timestamp=ts, received_at=ts)


def _fake_settings(**overrides):
    defaults = dict(
        realtime_enabled=True,
        realtime_watchlist="BTC",
        realtime_freshness_stale_seconds=300.0,
        realtime_candle_state_ttl_seconds=1200,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _redis_mock(get_return=None):
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=get_return)
    redis.set = AsyncMock()
    return redis


# ---- pure bucket math ---------------------------------------------------


def test_bucket_start_floors_to_the_five_minute_boundary():
    assert bucket_start(datetime(2026, 8, 25, 10, 37, 42, tzinfo=UTC)) == datetime(
        2026, 8, 25, 10, 35, tzinfo=UTC
    )
    assert bucket_start(datetime(2026, 8, 25, 10, 40, 0, tzinfo=UTC)) == datetime(
        2026, 8, 25, 10, 40, tzinfo=UTC
    )


def test_bucket_state_json_round_trips():
    state = BucketState.start(datetime(2026, 8, 25, 10, 35, tzinfo=UTC), _tick(price=100.0))
    restored = BucketState.from_json(state.to_json())
    assert restored == state


def test_bucket_state_extend_updates_high_low_close_and_tick_count():
    state = BucketState.start(datetime(2026, 8, 25, 10, 35, tzinfo=UTC), _tick(price=100.0))
    state.extend(_tick(price=105.0))
    state.extend(_tick(price=98.0))
    assert state.high == 105.0
    assert state.low == 98.0
    assert state.close == 98.0
    assert state.tick_count == 3


def test_to_candle_has_no_volume_and_names_the_sampling_method():
    state = BucketState.start(datetime(2026, 8, 25, 10, 35, tzinfo=UTC), _tick(price=100.0))
    candle = state.to_candle("BTC")
    assert candle.volume is None
    assert candle.source == "realtime_coinbase_1m_sampled"


# ---- aggregate_five_minute_candles --------------------------------------


async def test_aggregate_returns_early_when_realtime_is_disabled():
    with (
        patch(
            "app.services.realtime.aggregator.get_settings",
            return_value=_fake_settings(realtime_enabled=False),
        ),
        patch("app.services.realtime.aggregator.get_latest_ticks", AsyncMock()) as mock_ticks,
    ):
        result = await aggregator.aggregate_five_minute_candles(MagicMock(), _redis_mock())
    assert result == []
    mock_ticks.assert_not_awaited()


async def test_aggregate_starts_a_new_bucket_on_the_first_tick_and_finalizes_nothing():
    redis = _redis_mock(get_return=None)
    tick = _tick(price=100.0)
    with (
        patch("app.services.realtime.aggregator.get_settings", return_value=_fake_settings()),
        patch(
            "app.services.realtime.aggregator.get_latest_ticks",
            AsyncMock(return_value={"BTC": tick}),
        ),
        patch("app.services.realtime.aggregator.upsert_candles", AsyncMock()) as mock_upsert,
    ):
        result = await aggregator.aggregate_five_minute_candles(MagicMock(), redis)

    assert result == []
    mock_upsert.assert_not_awaited()
    redis.set.assert_awaited_once()
    key, payload = redis.set.call_args.args
    assert key == "realtime:candle:5m:BTC"
    state = json.loads(payload)
    assert state["open"] == 100.0
    assert state["tick_count"] == 1


async def test_aggregate_extends_an_existing_bucket_for_the_same_window():
    now = datetime.now(UTC)
    bucket = bucket_start(now)
    existing = BucketState.start(bucket, _tick(price=100.0, event_timestamp=bucket))
    redis = _redis_mock(get_return=existing.to_json())
    new_tick = _tick(price=110.0, event_timestamp=bucket + timedelta(minutes=1))

    with (
        patch("app.services.realtime.aggregator.get_settings", return_value=_fake_settings()),
        patch(
            "app.services.realtime.aggregator.get_latest_ticks",
            AsyncMock(return_value={"BTC": new_tick}),
        ),
        patch("app.services.realtime.aggregator.upsert_candles", AsyncMock()) as mock_upsert,
    ):
        result = await aggregator.aggregate_five_minute_candles(MagicMock(), redis)

    assert result == []
    mock_upsert.assert_not_awaited()
    saved_state = json.loads(redis.set.call_args.args[1])
    assert saved_state["high"] == 110.0
    assert saved_state["tick_count"] == 2


async def test_aggregate_finalizes_the_old_bucket_on_rollover_and_starts_a_fresh_one():
    old_bucket = bucket_start(datetime.now(UTC)) - timedelta(minutes=5)
    old_state = BucketState.start(old_bucket, _tick(price=100.0, event_timestamp=old_bucket))
    old_state.extend(_tick(price=120.0, event_timestamp=old_bucket + timedelta(minutes=2)))
    redis = _redis_mock(get_return=old_state.to_json())

    new_bucket = bucket_start(datetime.now(UTC))
    new_tick = _tick(price=150.0, event_timestamp=new_bucket)

    with (
        patch("app.services.realtime.aggregator.get_settings", return_value=_fake_settings()),
        patch(
            "app.services.realtime.aggregator.get_latest_ticks",
            AsyncMock(return_value={"BTC": new_tick}),
        ),
        patch("app.services.realtime.aggregator.upsert_candles", AsyncMock()) as mock_upsert,
        patch("app.services.realtime.aggregator.fill_missing_indicators", AsyncMock()),
        patch(
            "app.services.realtime.aggregator._roll_up_fifteen_minute", AsyncMock()
        ) as mock_roll_up,
    ):
        result = await aggregator.aggregate_five_minute_candles(MagicMock(), redis)

    assert result == ["BTC"]
    mock_upsert.assert_awaited_once()
    _, _, finalized_candles = mock_upsert.call_args.args
    assert len(finalized_candles) == 1
    assert finalized_candles[0].timestamp == old_bucket
    assert finalized_candles[0].high == 120.0
    assert finalized_candles[0].close == 120.0  # last tick recorded before rollover
    mock_roll_up.assert_awaited_once()

    # A fresh bucket for the new window was written, not a continuation of the old one.
    saved_state = json.loads(redis.set.call_args.args[1])
    assert saved_state["bucket_start"] == new_bucket.isoformat()
    assert saved_state["open"] == 150.0


async def test_aggregate_skips_a_stale_cached_tick_rather_than_fabricating_a_flat_candle():
    stale_tick = _tick(price=100.0, event_timestamp=datetime.now(UTC) - timedelta(hours=1))
    redis = _redis_mock(get_return=None)

    with (
        patch(
            "app.services.realtime.aggregator.get_settings",
            return_value=_fake_settings(realtime_freshness_stale_seconds=300.0),
        ),
        patch(
            "app.services.realtime.aggregator.get_latest_ticks",
            AsyncMock(return_value={"BTC": stale_tick}),
        ),
    ):
        result = await aggregator.aggregate_five_minute_candles(MagicMock(), redis)

    assert result == []
    redis.set.assert_not_awaited()
    redis.get.assert_not_awaited()  # never even looks up the bucket for a stale symbol


# ---- 15m roll-up: the ON CONFLICT DO NOTHING race-condition guard ------


async def test_roll_up_fifteen_minute_only_resamples_fully_elapsed_windows():
    now = datetime.now(UTC)
    current_15m_start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    completed_window_start = current_15m_start - timedelta(minutes=15)

    completed_rows = [
        SimpleNamespace(
            timestamp=completed_window_start + timedelta(minutes=i * 5),
            open=100.0 + i,
            high=102.0 + i,
            low=99.0 + i,
            close=101.0 + i,
            volume=None,
            source="realtime_coinbase_1m_sampled",
        )
        for i in range(3)
    ]
    # Still-forming window -- must NOT be included, or a premature/narrow
    # 15m candle would get permanently frozen by ON CONFLICT DO NOTHING.
    in_progress_row = SimpleNamespace(
        timestamp=current_15m_start,
        open=200.0,
        high=205.0,
        low=195.0,
        close=203.0,
        volume=None,
        source="realtime_coinbase_1m_sampled",
    )

    with (
        patch(
            "app.services.realtime.aggregator.get_series",
            AsyncMock(return_value=[*completed_rows, in_progress_row]),
        ),
        patch("app.services.realtime.aggregator.upsert_candles", AsyncMock()) as mock_upsert,
        patch("app.services.realtime.aggregator.fill_missing_indicators", AsyncMock()),
    ):
        await aggregator._roll_up_fifteen_minute(MagicMock(), "BTC")

    mock_upsert.assert_awaited_once()
    _, _, fifteen_min_candles = mock_upsert.call_args.args
    assert len(fifteen_min_candles) == 1
    assert fifteen_min_candles[0].timestamp == completed_window_start
    assert fifteen_min_candles[0].high == 104.0  # max across the 3 completed rows only
    assert fifteen_min_candles[0].volume is None  # min_count=1 sum of all-None stays None


async def test_roll_up_fifteen_minute_does_nothing_when_no_window_has_fully_elapsed_yet():
    now = datetime.now(UTC)
    current_15m_start = now.replace(minute=(now.minute // 15) * 15, second=0, microsecond=0)
    only_in_progress_row = SimpleNamespace(
        timestamp=current_15m_start,
        open=100.0,
        high=101.0,
        low=99.0,
        close=100.5,
        volume=None,
        source="realtime_coinbase_1m_sampled",
    )
    with (
        patch(
            "app.services.realtime.aggregator.get_series",
            AsyncMock(return_value=[only_in_progress_row]),
        ),
        patch("app.services.realtime.aggregator.upsert_candles", AsyncMock()) as mock_upsert,
    ):
        await aggregator._roll_up_fifteen_minute(MagicMock(), "BTC")
    mock_upsert.assert_not_awaited()
