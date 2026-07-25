"""Crypto Fear & Greed Index -- a real, free, no-key-required data source
(https://alternative.me/crypto/fear-and-greed-index/), unlike social-media
sentiment (Twitter/X, Reddit) or options-market sentiment (put/call skew),
neither of which has a free or already-configured source in this project.
Those are reported as honestly unavailable by SentimentEngine rather than
guessed -- this module only covers the one sub-signal that's actually real.
"""

import logging

import httpx

from app.config import get_settings
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

FEAR_GREED_URL = "https://api.alternative.me/fng/"


@default_retry()
async def _fetch(client: httpx.AsyncClient) -> dict:
    response = await client.get(FEAR_GREED_URL, params={"limit": 1, "format": "json"})
    response.raise_for_status()
    return response.json()


async def fetch_fear_greed_index() -> dict | None:
    """Returns {"value": int 0-100, "classification": str} or None if the
    upstream API is unreachable -- never a fabricated number."""
    settings = get_settings()
    try:
        async with build_http_client(settings.http_timeout_seconds) as client:
            payload = await _fetch(client)
    except Exception:
        logger.warning("Fear & Greed Index fetch failed", exc_info=True)
        return None

    data = payload.get("data") or []
    if not data:
        logger.warning("Fear & Greed Index returned no data")
        return None

    latest = data[0]
    try:
        return {
            "value": int(latest["value"]),
            "classification": str(latest["value_classification"]),
        }
    except (KeyError, ValueError, TypeError):
        logger.warning("Fear & Greed Index returned an unexpected shape: %s", latest)
        return None
