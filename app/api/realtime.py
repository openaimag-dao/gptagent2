import json
import logging

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.database.redis import get_redis
from app.services.realtime.collector import STATUS_CHANNEL, TICKS_CHANNEL
from app.services.realtime.config import parse_watchlist
from app.services.realtime.freshness import age_seconds, classify_freshness_from_settings
from app.services.realtime.schemas import RealtimePriceTick
from app.services.realtime.store import get_latest_ticks, get_status

router = APIRouter(prefix="/api/realtime", tags=["realtime"])

logger = logging.getLogger(__name__)

# How long pubsub.get_message() blocks waiting for a real tick before this
# generator yields a comment-only heartbeat -- keeps the connection alive
# through proxies/load balancers that time out idle streams.
_HEARTBEAT_SECONDS = 15.0


def _tick_payload(tick: RealtimePriceTick) -> dict:
    settings = get_settings()
    payload = tick.model_dump(mode="json")
    payload["freshness"] = classify_freshness_from_settings(age_seconds(tick.received_at), settings)
    payload["age_seconds"] = age_seconds(tick.received_at)
    return payload


async def _event_stream(request: Request):
    settings = get_settings()
    redis = get_redis()
    watchlist = parse_watchlist(settings.realtime_watchlist)

    # Last-known values first, so a newly-connected client sees real prices
    # immediately instead of a blank screen while waiting for the next tick.
    latest = await get_latest_ticks(redis, watchlist)
    for tick in latest.values():
        yield f"data: {json.dumps(_tick_payload(tick))}\n\n"

    status = await get_status(redis)
    yield f"event: status\ndata: {json.dumps(status)}\n\n"

    pubsub = redis.pubsub()
    await pubsub.subscribe(TICKS_CHANNEL, STATUS_CHANNEL)
    try:
        while True:
            if await request.is_disconnected():
                break
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=_HEARTBEAT_SECONDS
            )
            if message is None:
                yield ": heartbeat\n\n"
                continue
            if message["channel"] == TICKS_CHANNEL:
                tick = RealtimePriceTick.model_validate_json(message["data"])
                yield f"data: {json.dumps(_tick_payload(tick))}\n\n"
            else:
                yield f"event: status\ndata: {message['data']}\n\n"
    finally:
        await pubsub.unsubscribe(TICKS_CHANNEL, STATUS_CHANNEL)
        await pubsub.aclose()


@router.get("/prices")
async def stream_prices(request: Request) -> StreamingResponse:
    return StreamingResponse(
        _event_stream(request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/status")
async def realtime_status() -> dict:
    settings = get_settings()
    redis = get_redis()
    watchlist = parse_watchlist(settings.realtime_watchlist)
    status = await get_status(redis)
    latest = await get_latest_ticks(redis, watchlist)
    symbols = {
        symbol: {
            "price": tick.price,
            "age_seconds": age_seconds(tick.received_at),
            "freshness": classify_freshness_from_settings(age_seconds(tick.received_at), settings),
        }
        for symbol, tick in latest.items()
    }
    return {
        **status,
        "watchlist": watchlist,
        "symbols": symbols,
        # Config-driven thresholds (never hardcoded) so the frontend can
        # locally re-classify freshness between server pushes (a card
        # aging from LIVE to RECENT with no new tick yet) without
        # duplicating these numbers as a second hardcoded copy in JS.
        "freshness_thresholds": {
            "live_seconds": settings.realtime_freshness_live_seconds,
            "recent_seconds": settings.realtime_freshness_recent_seconds,
            "delayed_seconds": settings.realtime_freshness_delayed_seconds,
            "stale_seconds": settings.realtime_freshness_stale_seconds,
        },
    }
