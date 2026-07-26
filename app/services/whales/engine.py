"""Whale Intelligence: derivatives-market positioning via CoinGlass
(primary) with Coinalyze as a fallback when CoinGlass is unconfigured or
its call fails.

Exchange inflow/outflow, large-wallet tracking and stablecoin supply
changes require a genuine on-chain wallet tracker (e.g. Glassnode,
CryptoQuant) -- neither CoinGlass nor Coinalyze is one, they're
derivatives-market aggregators. Consistent with this project's rule of
never fabricating data, this engine only ever reports what those two
sources can genuinely provide (funding rate, open interest, 24h
liquidations, long/short ratio) and reports the rest as honestly
unavailable rather than inventing accumulation/distribution numbers from
data that doesn't support that conclusion.

`classification` is derived, not fetched: it labels *derivatives
positioning* (long-heavy / short-heavy / balanced), not on-chain
accumulation or distribution -- this project has no data source that
could honestly support that older, stronger claim.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import WhaleSnapshot
from app.database.redis import get_redis
from app.services.market.providers.cache import RedisCooldownCache
from app.services.whales.providers.coinalyze import CoinalyzeClient, CoinalyzeError
from app.services.whales.providers.coinglass import CoinGlassClient, CoinGlassError

logger = logging.getLogger(__name__)

_RESPONSE_FIELDS = (
    "funding_rate",
    "open_interest",
    "liquidations_24h",
    "long_short_ratio",
    "classification",  # derived from funding_rate/long_short_ratio; see module docstring
)
_CACHE_TTL_SECONDS = 300
# Long/short ratio and funding rate thresholds beyond which leveraged
# positioning is lopsided enough to flag; not a prediction, just a
# description of the current derivatives book.
_RATIO_HIGH = 1.5
_RATIO_LOW = 1 / 1.5


def _classify(snapshot: dict[str, float]) -> str | None:
    ratio = snapshot.get("long_short_ratio")
    funding = snapshot.get("funding_rate")
    if ratio is None and funding is None:
        return None
    if (ratio is not None and ratio >= _RATIO_HIGH) or (funding is not None and funding > 0.0005):
        return "long_heavy"
    if (ratio is not None and ratio <= _RATIO_LOW) or (funding is not None and funding < -0.0005):
        return "short_heavy"
    return "balanced"


class WhaleIntelligenceEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        coinglass: CoinGlassClient | None = None,
        coinalyze: CoinalyzeClient | None = None,
    ) -> None:
        self._settings = get_settings()
        self._session_factory = session_factory
        self._coinglass = coinglass or CoinGlassClient()
        self._coinalyze = coinalyze or CoinalyzeClient()
        self._cache = RedisCooldownCache(get_redis(), "whale_derivatives")

    async def get_snapshot(self, symbol: str = "BTC") -> dict:
        symbol = symbol.upper()
        cached = await self._cache.get(symbol)
        if cached is not None:
            return cached

        data: dict[str, float] = {}
        source: str | None = None

        if self._coinglass.configured:
            try:
                data = await self._coinglass.get_snapshot(symbol)
                source = "coinglass"
            except CoinGlassError as exc:
                logger.warning("CoinGlass snapshot failed for %s: %s", symbol, exc)

        if not data and self._coinalyze.configured:
            try:
                data = await self._coinalyze.get_snapshot(symbol)
                source = "coinalyze"
            except CoinalyzeError as exc:
                logger.warning("Coinalyze snapshot failed for %s: %s", symbol, exc)

        if not data:
            result = {
                "available": False,
                "symbol": symbol,
                "reason": (
                    "Neither COINGLASS_API_KEY nor COINALYZE_API_KEY is configured (or both "
                    "calls failed); derivatives-market data (funding rate, open interest, "
                    "liquidations, long/short ratio) is unavailable this cycle."
                ),
                "would_return": list(_RESPONSE_FIELDS),
            }
            await self._cache.set(symbol, result, _CACHE_TTL_SECONDS)
            return result

        result = {
            "available": True,
            "symbol": symbol,
            "source": source,
            "classification": _classify(data),
            **data,
        }
        await self._cache.set(symbol, result, _CACHE_TTL_SECONDS)
        return result

    async def compute_and_store(self, symbol: str = "BTC") -> WhaleSnapshot:
        """Persists the current get_snapshot() read (including an honest
        "unavailable" read) so Market Memory and the Smart Alert Engine have
        real history to compare against. Requires a session_factory."""
        if self._session_factory is None:
            raise RuntimeError("WhaleIntelligenceEngine needs a session_factory to persist")

        snapshot = await self.get_snapshot(symbol)
        row = WhaleSnapshot(
            symbol=symbol.upper(),
            available=snapshot["available"],
            classification=snapshot.get("classification"),
            reason=snapshot.get("reason"),
            data=snapshot,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def get_latest(self, symbol: str = "BTC") -> WhaleSnapshot | None:
        if self._session_factory is None:
            raise RuntimeError("WhaleIntelligenceEngine needs a session_factory to query history")
        async with self._session_factory() as session:
            return await session.scalar(
                select(WhaleSnapshot)
                .where(WhaleSnapshot.symbol == symbol.upper())
                .order_by(WhaleSnapshot.computed_at.desc())
                .limit(1)
            )
