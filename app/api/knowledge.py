from fastapi import APIRouter, HTTPException, Query

from app.database.session import get_session_factory
from app.services.history.registry import find_symbol_config
from app.services.history.schemas import Timeframe
from app.services.knowledge.engine import KnowledgeEngine

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


@router.get("/{symbol}")
async def get_knowledge(
    symbol: str,
    timeframe: str = Query("1d", description="1d, 4h or 1h"),
    k: int = Query(5, ge=1, le=20),
) -> dict:
    config = find_symbol_config(symbol)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Unknown historical symbol: {symbol}")

    try:
        tf = Timeframe(timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {timeframe}") from exc

    engine = KnowledgeEngine(get_session_factory())
    analogs = await engine.find_analogs(config.symbol, config.model, tf, k=k)
    if not analogs:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Not enough synced history for {config.symbol}/{timeframe} to find analogs "
                "yet -- run sync_history.py first"
            ),
        )

    return {
        "symbol": config.symbol,
        "timeframe": timeframe,
        "analogs": [
            {
                "timestamp": a["timestamp"].isoformat(),
                "rsi": a["rsi"],
                "volatility": a["volatility"],
                "distance": a["distance"],
                "forward_return_pct": a["forward_return_pct"],
                "nearby_events": a["nearby_events"],
            }
            for a in analogs
        ],
    }
