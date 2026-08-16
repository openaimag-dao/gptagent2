import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.realtime.binance_client import parse_ticker_message, to_binance_pair
from app.services.realtime.collector import (
    LATEST_KEY_PREFIX,
    STATUS_CHANNEL,
    STATUS_KEY,
    TICKS_CHANNEL,
    RealtimePriceCollector,
)
from app.services.realtime.schemas import RealtimePriceTick


class _AlwaysFailingClient:
    async def stream(self):
        raise RuntimeError("connection refused")
        yield  # pragma: no cover -- makes this an async generator


class _OneTickThenFailsClient:
    def __init__(self, tick: RealtimePriceTick):
        self._tick = tick

    async def stream(self):
        yield self._tick
        raise RuntimeError("connection dropped")


def _tick(symbol="BTC", price=100000.0):
    now = datetime.now(UTC)
    return RealtimePriceTick(
        symbol=symbol, price=price, source="binance", event_timestamp=now, received_at=now
    )


async def test_run_backs_off_with_the_configured_capped_sequence_never_a_tight_loop():
    redis = AsyncMock()
    collector = RealtimePriceCollector(_AlwaysFailingClient(), redis, [1.0, 2.0, 5.0])
    recorded_delays = []

    async def _fake_sleep(delay):
        recorded_delays.append(delay)
        if len(recorded_delays) >= 5:
            raise asyncio.CancelledError()

    with patch("app.services.realtime.collector.asyncio.sleep", _fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await collector.run()

    # Walks the configured sequence, then holds at the last (largest) step
    # -- never zero/negative, never unbounded.
    assert recorded_delays == [1.0, 2.0, 5.0, 5.0, 5.0]


async def test_run_resets_backoff_after_a_successful_tick():
    redis = AsyncMock()
    tick = _tick()
    collector = RealtimePriceCollector(_OneTickThenFailsClient(tick), redis, [1.0, 2.0, 5.0])
    recorded_delays = []

    async def _fake_sleep(delay):
        recorded_delays.append(delay)
        if len(recorded_delays) >= 2:
            raise asyncio.CancelledError()

    with patch("app.services.realtime.collector.asyncio.sleep", _fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await collector.run()

    # Every attempt receives one tick before failing, so backoff always
    # resets to the first (smallest) step rather than climbing.
    assert recorded_delays == [1.0, 1.0]


async def test_run_publishes_each_tick_and_caches_the_latest_value():
    redis = AsyncMock()
    tick = _tick(symbol="ETH", price=3500.0)
    collector = RealtimePriceCollector(_OneTickThenFailsClient(tick), redis, [1.0])

    async def _fake_sleep(_delay):
        raise asyncio.CancelledError()

    with patch("app.services.realtime.collector.asyncio.sleep", _fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await collector.run()

    redis.publish.assert_any_call(TICKS_CHANNEL, tick.model_dump_json())
    redis.set.assert_any_call(f"{LATEST_KEY_PREFIX}ETH", tick.model_dump_json(), ex=3600)


async def test_run_reports_connected_status_while_ticks_are_flowing():
    redis = AsyncMock()
    tick = _tick()
    collector = RealtimePriceCollector(_OneTickThenFailsClient(tick), redis, [1.0])

    async def _fake_sleep(_delay):
        raise asyncio.CancelledError()

    with patch("app.services.realtime.collector.asyncio.sleep", _fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await collector.run()

    statuses = [
        call.args[0] for call in redis.publish.call_args_list if call.args[0] == STATUS_CHANNEL
    ]
    assert len(statuses) >= 1
    # The CONNECTED status write happens before the disconnect/backoff path.
    set_calls = [call.args for call in redis.set.call_args_list if call.args[0] == STATUS_KEY]
    assert any('"status": "connected"' in payload for _key, payload in set_calls)


def test_to_binance_pair_lowercases_and_appends_usdt():
    assert to_binance_pair("BTC") == "btcusdt"
    assert to_binance_pair(" eth ") == "ethusdt"


def test_parse_ticker_message_normalizes_a_combined_stream_envelope():
    raw = (
        '{"stream": "btcusdt@ticker", "data": '
        '{"s": "BTCUSDT", "c": "100000.5", "p": "1200.0", "P": "1.22", '
        '"v": "50000", "h": "101000", "l": "98000", "E": 1735689600000}}'
    )
    tick = parse_ticker_message(raw)
    assert tick is not None
    assert tick.symbol == "BTC"
    assert tick.price == 100000.5
    assert tick.change_24h == 1200.0
    assert tick.change_pct_24h == 1.22
    assert tick.volume_24h == 50000.0
    assert tick.high_24h == 101000.0
    assert tick.low_24h == 98000.0
    assert tick.source == "binance"


def test_parse_ticker_message_returns_none_for_malformed_input_instead_of_raising():
    assert parse_ticker_message("not json at all") is None
    assert parse_ticker_message('{"stream": "btcusdt@ticker", "data": {}}') is None
