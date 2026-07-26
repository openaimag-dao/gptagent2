from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.market.repository import MarketRepository
from app.services.portfolio.engine import PortfolioEngine

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


class AddPositionRequest(BaseModel):
    symbol: str
    quantity: float
    entry_price: float | None = None


def _build_engine() -> PortfolioEngine:
    session_factory = get_session_factory()
    return PortfolioEngine(session_factory, MarketRepository(session_factory, get_redis()))


def _serialize_position(position) -> dict:
    return {
        "id": position.id,
        "symbol": position.symbol,
        "quantity": float(position.quantity),
        "entry_price": float(position.entry_price) if position.entry_price is not None else None,
        "added_at": position.added_at.isoformat(),
    }


@router.get("")
async def get_portfolio(name: str = Query("main")) -> dict:
    engine = _build_engine()
    portfolio = await engine.get_or_create(name)
    health = await engine.compute_health(portfolio.id)
    return {"portfolio_id": portfolio.id, "name": portfolio.name, **health}


@router.post("/positions")
async def add_position(request: AddPositionRequest, name: str = Query("main")) -> dict:
    engine = _build_engine()
    portfolio = await engine.get_or_create(name)
    try:
        position = await engine.add_position(
            portfolio.id, request.symbol, request.quantity, request.entry_price
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _serialize_position(position)


@router.delete("/positions/{position_id}")
async def remove_position(position_id: int) -> dict:
    engine = _build_engine()
    removed = await engine.remove_position(position_id)
    if not removed:
        raise HTTPException(status_code=404, detail=f"No position with id {position_id}")
    return {"removed": True, "position_id": position_id}
