from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.market.repository import MarketRepository

router = APIRouter(prefix="/api/market", tags=["market"])


def _get_repository() -> MarketRepository:
    return MarketRepository(get_session_factory(), get_redis())


@router.get("")
async def get_latest_market_data() -> dict:
    """Latest collected snapshot, served from the Redis cache when available."""
    repository = _get_repository()

    cached = await repository.get_latest_from_cache()
    if cached is not None:
        return cached

    assets = await repository.get_latest()
    if not assets:
        raise HTTPException(status_code=404, detail="No market data collected yet")

    return {
        "collected_at": assets[0].recorded_at.isoformat(),
        "quotes": [
            {
                "symbol": asset.symbol,
                "name": asset.name,
                "asset_class": asset.asset_class.value,
                "price": float(asset.price),
                "change_24h": float(asset.change_24h) if asset.change_24h is not None else None,
                "change_pct_24h": (
                    float(asset.change_pct_24h) if asset.change_pct_24h is not None else None
                ),
                "market_cap": float(asset.market_cap) if asset.market_cap is not None else None,
                "volume_24h": float(asset.volume_24h) if asset.volume_24h is not None else None,
                "source": asset.source,
            }
            for asset in assets
        ],
        "errors": [],
    }


@router.get("/{symbol}/history")
async def get_symbol_history(symbol: str, days: int = Query(default=7, ge=1, le=90)) -> dict:
    repository = _get_repository()
    since = datetime.now(UTC) - timedelta(days=days)
    history = await repository.get_history(symbol, since)
    if not history:
        raise HTTPException(
            status_code=404, detail=f"No history found for symbol '{symbol.upper()}'"
        )

    return {
        "symbol": symbol.upper(),
        "days": days,
        "points": [
            {"recorded_at": item.recorded_at.isoformat(), "price": float(item.price)}
            for item in history
        ],
    }
