from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.market.repository import MarketRepository
from app.services.realtime.freshness import age_seconds, classify_freshness_from_settings

router = APIRouter(prefix="/api/market", tags=["market"])


def _get_repository() -> MarketRepository:
    return MarketRepository(get_session_factory(), get_redis())


def _annotate_freshness(quotes: list[dict], collected_at: datetime) -> list[dict]:
    """Every quote in a batch is collected in the same cycle, so they share
    one `collected_at` -- honestly reflects the real per-batch granularity
    rather than fabricating independent per-quote timestamps that don't
    exist. Root-cause fix: previously neither this response shape nor the
    dashboard had any way to tell a fresh price from one served from a
    15-minute-old cache entry."""
    settings = get_settings()
    age = age_seconds(collected_at)
    freshness = classify_freshness_from_settings(age, settings)
    return [{**quote, "freshness": freshness, "age_seconds": age} for quote in quotes]


@router.get("")
async def get_latest_market_data() -> dict:
    """Latest collected snapshot, served from the Redis cache when available."""
    repository = _get_repository()

    cached = await repository.get_latest_from_cache()
    if cached is not None:
        cached["quotes"] = _annotate_freshness(
            cached["quotes"], datetime.fromisoformat(cached["collected_at"])
        )
        return cached

    assets = await repository.get_latest()
    if not assets:
        raise HTTPException(status_code=404, detail="No market data collected yet")

    collected_at = assets[0].recorded_at
    quotes = [
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
    ]

    return {
        "collected_at": collected_at.isoformat(),
        "quotes": _annotate_freshness(quotes, collected_at),
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
