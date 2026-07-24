from fastapi import APIRouter, HTTPException

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.market.repository import MarketRepository

router = APIRouter(prefix="/api/btc", tags=["market"])


@router.get("")
async def get_btc() -> dict:
    """Dedicated Bitcoin endpoint -- the spec's headline asset gets its own route."""
    repository = MarketRepository(get_session_factory(), get_redis())
    assets = await repository.get_latest()
    asset = next((a for a in assets if a.symbol == "BTC"), None)
    if asset is None:
        raise HTTPException(status_code=404, detail="No BTC data collected yet")

    return {
        "symbol": asset.symbol,
        "name": asset.name,
        "price": float(asset.price),
        "change_24h": float(asset.change_24h) if asset.change_24h is not None else None,
        "change_pct_24h": (
            float(asset.change_pct_24h) if asset.change_pct_24h is not None else None
        ),
        "market_cap": float(asset.market_cap) if asset.market_cap is not None else None,
        "volume_24h": float(asset.volume_24h) if asset.volume_24h is not None else None,
        "source": asset.source,
        "recorded_at": asset.recorded_at.isoformat(),
    }
