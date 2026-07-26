"""A tiny Redis-backed cooldown cache.

Twelve Data's free tier is 800 credits/day and Alpha Vantage's is 5
requests/minute (25/day for News & Sentiment) -- calling either on the
existing 5-minute market-data scheduler tick would exhaust a day's quota
in under an hour. This cache lets a provider say "don't actually call the
upstream API more than once every N seconds", persisted in Redis (the
project's existing cache store, see app/database/redis.py) rather than an
in-process dict, so the cooldown survives process restarts and works the
same whether one worker or several are running.
"""

import json
import logging

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class RedisCooldownCache:
    def __init__(self, redis_client: Redis, namespace: str) -> None:
        self._redis = redis_client
        self._namespace = namespace

    def _key(self, key: str) -> str:
        return f"provider_cooldown:{self._namespace}:{key}"

    async def get(self, key: str) -> list | dict | None:
        raw = await self._redis.get(self._key(key))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            logger.warning("Corrupt cooldown cache entry for %s/%s", self._namespace, key)
            return None

    async def set(self, key: str, value: list | dict, ttl_seconds: int) -> None:
        await self._redis.set(self._key(key), json.dumps(value), ex=ttl_seconds)
