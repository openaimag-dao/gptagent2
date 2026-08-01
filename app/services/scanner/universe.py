"""v5.5 Market Scanner universe: the top ~500 cryptocurrencies by market
cap, refreshed every `scanner_universe_refresh_hours` (default 24h) and
cached in Redis so every scan cycle in between reuses the same ranked list
rather than re-fetching it. The mission's "always include" symbols are
merged in on every refresh even if they've fallen out of the top N --
looked up individually by CoinGecko id so they're never silently dropped.
"""

import json
import logging

from redis.asyncio import Redis

from app.config import get_settings
from app.services.scanner.provider import CoinGeckoMarketsClient

logger = logging.getLogger(__name__)

UNIVERSE_CACHE_KEY = "scanner:universe"

# Mission-mandated "always include, even outside the Top 500" list, mapped
# to their CoinGecko coin ids for the individual-lookup fallback.
ALWAYS_INCLUDE: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "BNB": "binancecoin",
    "XRP": "ripple",
    "ADA": "cardano",
    "DOGE": "dogecoin",
    "LINK": "chainlink",
    "AVAX": "avalanche-2",
    "TRX": "tron",
    "TON": "the-open-network",
}


def _normalize(coin: dict) -> dict:
    return {
        "symbol": coin["symbol"].upper(),
        "name": coin["name"],
        "coingecko_id": coin["id"],
        "market_cap_rank": coin.get("market_cap_rank"),
    }


class ScannerUniverse:
    def __init__(self, client: CoinGeckoMarketsClient, redis_client: Redis | None) -> None:
        self._client = client
        self._redis = redis_client
        self._settings = get_settings()

    async def _fetch_fresh(self, top_n: int) -> list[dict]:
        top = await self._client.fetch_top(top_n)
        entries = {c["symbol"].upper(): _normalize(c) for c in top}

        missing_ids = [
            coingecko_id for symbol, coingecko_id in ALWAYS_INCLUDE.items() if symbol not in entries
        ]
        if missing_ids:
            extra = await self._client.fetch_by_ids(missing_ids)
            for coin in extra:
                normalized = _normalize(coin)
                entries[normalized["symbol"]] = normalized

        return sorted(entries.values(), key=lambda e: e["market_cap_rank"] or 10_000)

    async def _cached(self) -> list[dict] | None:
        if self._redis is None:
            return None
        cached = await self._redis.get(UNIVERSE_CACHE_KEY)
        return json.loads(cached) if cached else None

    async def _store(self, universe: list[dict]) -> None:
        if self._redis is None:
            return
        ttl_seconds = self._settings.scanner_universe_refresh_hours * 3600
        await self._redis.set(UNIVERSE_CACHE_KEY, json.dumps(universe), ex=ttl_seconds)

    async def get_universe(self, top_n: int = 500) -> list[dict]:
        """The cached universe, fetching fresh only on a cache miss (first
        run, or the cache's own `scanner_universe_refresh_hours` TTL
        having expired)."""
        cached = await self._cached()
        if cached is not None:
            return cached
        universe = await self._fetch_fresh(top_n)
        await self._store(universe)
        return universe

    async def refresh(self, top_n: int = 500) -> list[dict]:
        """Forces a fresh fetch, bypassing the cache -- called by the
        dedicated universe-refresh job on its own
        `scanner_universe_refresh_hours` cadence."""
        universe = await self._fetch_fresh(top_n)
        await self._store(universe)
        return universe
