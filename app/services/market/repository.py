import json
import logging
from datetime import datetime

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import AssetPrice, SnapshotBatch
from app.services.market.schemas import MarketSnapshotResult

logger = logging.getLogger(__name__)

LATEST_SNAPSHOT_CACHE_KEY = "market:latest_snapshot"


class MarketRepository:
    """Persists collected market snapshots to Postgres and caches the latest one in Redis."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis_client: Redis | None = None,
        cache_ttl_seconds: int = 900,
    ) -> None:
        self._session_factory = session_factory
        self._redis = redis_client
        self._cache_ttl_seconds = cache_ttl_seconds

    async def save_batch(self, snapshot: MarketSnapshotResult) -> None:
        async with self._session_factory() as session:
            batch = SnapshotBatch(id=snapshot.batch_id, collected_at=snapshot.collected_at)
            session.add(batch)
            for quote in snapshot.quotes:
                session.add(
                    AssetPrice(
                        batch_id=snapshot.batch_id,
                        symbol=quote.symbol,
                        name=quote.name,
                        asset_class=quote.asset_class,
                        price=quote.price,
                        change_24h=quote.change_24h,
                        change_pct_24h=quote.change_pct_24h,
                        market_cap=quote.market_cap,
                        volume_24h=quote.volume_24h,
                        source=quote.source,
                        extra=quote.extra,
                        recorded_at=snapshot.collected_at,
                    )
                )
            await session.commit()

        if self._redis is not None:
            payload = {
                "batch_id": str(snapshot.batch_id),
                "collected_at": snapshot.collected_at.isoformat(),
                "quotes": [q.model_dump(mode="json") for q in snapshot.quotes],
                "errors": snapshot.errors,
            }
            await self._redis.set(
                LATEST_SNAPSHOT_CACHE_KEY, json.dumps(payload), ex=self._cache_ttl_seconds
            )

    async def get_latest_from_cache(self) -> dict | None:
        if self._redis is None:
            return None
        raw = await self._redis.get(LATEST_SNAPSHOT_CACHE_KEY)
        return json.loads(raw) if raw else None

    async def get_latest(self) -> list[AssetPrice]:
        async with self._session_factory() as session:
            latest_batch_id = await session.scalar(
                select(SnapshotBatch.id).order_by(SnapshotBatch.collected_at.desc()).limit(1)
            )
            if latest_batch_id is None:
                return []
            result = await session.scalars(
                select(AssetPrice)
                .where(AssetPrice.batch_id == latest_batch_id)
                .order_by(AssetPrice.asset_class, AssetPrice.symbol)
            )
            return list(result)

    async def get_history(self, symbol: str, since: datetime) -> list[AssetPrice]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(AssetPrice)
                .where(AssetPrice.symbol == symbol.upper(), AssetPrice.recorded_at >= since)
                .order_by(AssetPrice.recorded_at.asc())
            )
            return list(result)
