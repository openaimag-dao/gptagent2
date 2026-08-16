"""Read-side helpers over the Redis state RealtimePriceCollector writes --
kept separate from collector.py so the API layer (SSE/status endpoints)
never needs to import the WebSocket client machinery, and so both sides
can be tested independently."""

import json

from redis.asyncio import Redis

from app.services.realtime.collector import LATEST_KEY_PREFIX, STATUS_KEY
from app.services.realtime.schemas import RealtimePriceTick


async def get_latest_ticks(redis: Redis, watchlist: list[str]) -> dict[str, RealtimePriceTick]:
    ticks: dict[str, RealtimePriceTick] = {}
    for symbol in watchlist:
        raw = await redis.get(f"{LATEST_KEY_PREFIX}{symbol}")
        if raw is not None:
            ticks[symbol] = RealtimePriceTick.model_validate_json(raw)
    return ticks


async def get_status(redis: Redis) -> dict:
    """Never fabricates a status: if the collector hasn't written
    realtime:status yet (e.g. just after startup, or realtime disabled),
    honestly reports "offline" rather than guessing "connected"."""
    raw = await redis.get(STATUS_KEY)
    if raw is None:
        return {"status": "offline", "updated_at": None}
    return json.loads(raw)
