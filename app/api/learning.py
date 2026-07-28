from fastapi import APIRouter, HTTPException, Query

from app.database.session import get_session_factory
from app.services.history.registry import find_symbol_config
from app.services.history.schemas import Timeframe
from app.services.learning.engine import LearningEngine

router = APIRouter(prefix="/api/learning", tags=["learning"])


@router.get("/{symbol}")
async def get_learning(
    symbol: str, timeframe: str = Query("1d", description="1d, 4h or 1h")
) -> dict:
    config = find_symbol_config(symbol)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Unknown historical symbol: {symbol}")

    try:
        tf = Timeframe(timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {timeframe}") from exc

    engine = LearningEngine(get_session_factory())
    result = await engine.evaluate_accuracy(config.symbol, config.model, tf)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No graded predictions yet for {config.symbol}/{timeframe} -- "
                "a prediction only counts once its horizon has actually elapsed "
                "in the stored history"
            ),
        )
    return result
