"""Runs the Coinbase WebSocket stream forever (until cancelled), publishing
every tick to Redis for /api/realtime to fan out over SSE. Reconnects with
a capped exponential backoff on disconnect -- never an unbounded or tight
retry loop (see app.config.settings.realtime_reconnect_backoff_seconds).
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.config import get_settings
from app.database.redis import get_redis
from app.services.realtime.coinbase_client import CoinbaseRealtimeClient
from app.services.realtime.config import parse_backoff_seconds, parse_watchlist
from app.services.realtime.schemas import ConnectionStatus, RealtimePriceTick

logger = logging.getLogger(__name__)

LATEST_KEY_PREFIX = "realtime:latest:"
TICKS_CHANNEL = "realtime:ticks"
STATUS_KEY = "realtime:status"
STATUS_CHANNEL = "realtime:status:events"
# Safety net only -- freshness is computed from event_timestamp/received_at,
# not this TTL. Just clears a symbol's last-known value if it's ever
# dropped from the watchlist instead of caching it forever.
_LATEST_TTL_SECONDS = 3600


class RealtimePriceCollector:
    def __init__(
        self,
        client: CoinbaseRealtimeClient,
        redis: Redis,
        backoff_seconds: list[float],
    ) -> None:
        self._client = client
        self._redis = redis
        self._backoff_seconds = backoff_seconds or [30.0]

    async def run(self) -> None:
        """Connects, streams ticks, and on any disconnect waits at least
        the first configured backoff step before retrying -- resets to the
        start of the sequence after a tick is actually received, and holds
        at the last (largest) step rather than growing unbounded once the
        sequence is exhausted."""
        backoff_index = 0
        while True:
            try:
                await self._set_status(ConnectionStatus.CONNECTING)
                async for tick in self._client.stream():
                    backoff_index = 0
                    await self._set_status(ConnectionStatus.CONNECTED)
                    await self._publish_tick(tick)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Realtime collector disconnected; reconnecting", exc_info=True)

            settled_offline = backoff_index >= len(self._backoff_seconds) - 1
            await self._set_status(
                ConnectionStatus.OFFLINE if settled_offline else ConnectionStatus.RECONNECTING
            )
            delay = self._backoff_seconds[min(backoff_index, len(self._backoff_seconds) - 1)]
            await asyncio.sleep(delay)
            backoff_index += 1

    async def _set_status(self, status: ConnectionStatus) -> None:
        payload = json.dumps({"status": status.value, "updated_at": datetime.now(UTC).isoformat()})
        await self._redis.set(STATUS_KEY, payload)
        await self._redis.publish(STATUS_CHANNEL, payload)

    async def _publish_tick(self, tick: RealtimePriceTick) -> None:
        payload = tick.model_dump_json()
        await self._redis.set(f"{LATEST_KEY_PREFIX}{tick.symbol}", payload, ex=_LATEST_TTL_SECONDS)
        await self._redis.publish(TICKS_CHANNEL, payload)


def build_realtime_collector() -> RealtimePriceCollector:
    settings = get_settings()
    watchlist = parse_watchlist(settings.realtime_watchlist)
    backoff = parse_backoff_seconds(settings.realtime_reconnect_backoff_seconds)
    client = CoinbaseRealtimeClient(settings.realtime_ws_url, watchlist)
    return RealtimePriceCollector(client, get_redis(), backoff)
