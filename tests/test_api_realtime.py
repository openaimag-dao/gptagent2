from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.realtime import _event_stream, _tick_payload, realtime_status
from app.services.realtime.collector import TICKS_CHANNEL
from app.services.realtime.schemas import RealtimePriceTick


def _settings_stub(**overrides):
    base = {
        "realtime_watchlist": "BTC,ETH",
        "realtime_freshness_live_seconds": 5.0,
        "realtime_freshness_recent_seconds": 30.0,
        "realtime_freshness_delayed_seconds": 120.0,
        "realtime_freshness_stale_seconds": 300.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _tick(symbol="BTC", price=100000.0, seconds_ago=0.0):
    received = datetime.now(UTC) - timedelta(seconds=seconds_ago)
    return RealtimePriceTick(
        symbol=symbol, price=price, source="binance", event_timestamp=received, received_at=received
    )


class _FakeDisconnectingRequest:
    """is_disconnected() returns False the first `disconnect_after` calls,
    then True -- lets the event-stream generator's while-True loop
    terminate deterministically in a test instead of needing a timeout."""

    def __init__(self, disconnect_after: int):
        self._calls = 0
        self._disconnect_after = disconnect_after

    async def is_disconnected(self) -> bool:
        self._calls += 1
        return self._calls > self._disconnect_after


class _FakePubSub:
    def __init__(self, messages):
        self._messages = list(messages)

    async def subscribe(self, *_channels):
        pass

    async def get_message(self, ignore_subscribe_messages=True, timeout=0.0):
        if self._messages:
            return self._messages.pop(0)
        return None

    async def unsubscribe(self, *_channels):
        pass

    async def aclose(self):
        pass


def test_tick_payload_adds_freshness_and_age_seconds():
    tick = _tick(seconds_ago=2.0)
    with patch("app.api.realtime.get_settings", return_value=_settings_stub()):
        payload = _tick_payload(tick)

    assert payload["symbol"] == "BTC"
    assert payload["freshness"] == "live"
    assert payload["age_seconds"] >= 2.0


def test_tick_payload_reports_stale_bands_honestly():
    tick = _tick(seconds_ago=250.0)
    with patch("app.api.realtime.get_settings", return_value=_settings_stub()):
        payload = _tick_payload(tick)

    assert payload["freshness"] == "stale"


async def test_event_stream_emits_last_known_value_then_status_then_pubsub_ticks():
    latest_btc = _tick(symbol="BTC", price=100000.0)
    redis = AsyncMock()
    redis.get.side_effect = lambda key: (
        latest_btc.model_dump_json() if key == "realtime:latest:BTC" else None
    )
    new_eth_tick = _tick(symbol="ETH", price=3500.0)
    # Redis.pubsub() is synchronous (returns a PubSub object directly, not
    # a coroutine) -- AsyncMock's default auto-mocking would wrongly make
    # it awaitable, so this is configured explicitly as a plain callable.
    redis.pubsub = MagicMock(
        return_value=_FakePubSub(
            [{"channel": TICKS_CHANNEL, "data": new_eth_tick.model_dump_json()}]
        )
    )
    request = _FakeDisconnectingRequest(disconnect_after=1)

    with (
        patch("app.api.realtime.get_settings", return_value=_settings_stub()),
        patch("app.api.realtime.get_redis", return_value=redis),
    ):
        events = [chunk async for chunk in _event_stream(request)]

    assert any('"symbol": "BTC"' in e and e.startswith("data:") for e in events)
    assert any(e.startswith("event: status") for e in events)
    assert any('"symbol": "ETH"' in e for e in events)


async def test_event_stream_yields_a_heartbeat_when_no_message_arrives():
    redis = AsyncMock()
    redis.get.return_value = None
    redis.pubsub = MagicMock(return_value=_FakePubSub([]))  # never yields a real message
    request = _FakeDisconnectingRequest(disconnect_after=1)

    with (
        patch("app.api.realtime.get_settings", return_value=_settings_stub()),
        patch("app.api.realtime.get_redis", return_value=redis),
    ):
        events = [chunk async for chunk in _event_stream(request)]

    assert ": heartbeat\n\n" in events


async def test_realtime_status_returns_thresholds_and_per_symbol_freshness():
    tick = _tick(symbol="BTC", seconds_ago=1.0)
    redis = AsyncMock()
    redis.get.side_effect = lambda key: (
        tick.model_dump_json() if key == "realtime:latest:BTC" else None
    )

    with (
        patch("app.api.realtime.get_settings", return_value=_settings_stub()),
        patch("app.api.realtime.get_redis", return_value=redis),
    ):
        result = await realtime_status()

    assert result["watchlist"] == ["BTC", "ETH"]
    assert result["symbols"]["BTC"]["freshness"] == "live"
    assert "ETH" not in result["symbols"]  # honestly omitted -- no tick received yet
    assert result["freshness_thresholds"]["live_seconds"] == 5.0
    assert "status" in result
