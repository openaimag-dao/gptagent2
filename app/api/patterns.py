from fastapi import APIRouter, HTTPException, Query

from app.database.session import get_session_factory
from app.services.history.registry import find_symbol_config
from app.services.history.schemas import Timeframe
from app.services.patterns.engine import PatternEngine

router = APIRouter(prefix="/api/patterns", tags=["patterns"])


@router.get("/{symbol}")
async def get_patterns(
    symbol: str,
    timeframe: str = Query("1d", description="1d, 4h or 1h"),
    limit: int = Query(10, ge=1, le=100),
) -> dict:
    config = find_symbol_config(symbol)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Unknown historical symbol: {symbol}")

    try:
        tf = Timeframe(timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {timeframe}") from exc

    session_factory = get_session_factory()
    engine = PatternEngine(session_factory)
    await engine.compute_and_store(config.symbol, config.model, tf)
    patterns = await engine.get_latest(config.symbol, tf, limit=limit)

    return {
        "symbol": config.symbol,
        "timeframe": timeframe,
        "count": len(patterns),
        "patterns": [
            {
                "timestamp": p.timestamp.isoformat(),
                "pattern_name": p.pattern_name,
                "direction": p.direction.value,
            }
            for p in patterns
        ],
    }
