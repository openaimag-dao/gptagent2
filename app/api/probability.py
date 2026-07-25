from fastapi import APIRouter, HTTPException, Query

from app.database.session import get_session_factory
from app.services.history.registry import find_symbol_config
from app.services.history.schemas import Timeframe
from app.services.probability.engine import ProbabilityEngine

router = APIRouter(prefix="/api/probability", tags=["probability"])


@router.get("/{symbol}")
async def get_probability(
    symbol: str, timeframe: str = Query("1d", description="1d, 4h or 1h")
) -> dict:
    config = find_symbol_config(symbol)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Unknown historical symbol: {symbol}")

    try:
        tf = Timeframe(timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {timeframe}") from exc

    engine = ProbabilityEngine(get_session_factory())
    snapshot = await engine.compute_and_store(config.symbol, config.model, tf)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"Not enough synced history for {config.symbol}/{timeframe} to compute a "
                "probability yet -- run sync_history.py first"
            ),
        )

    return {
        "symbol": snapshot.symbol,
        "timeframe": snapshot.timeframe,
        "horizon_periods": snapshot.horizon_periods,
        "reference_rsi": float(snapshot.reference_rsi),
        "sample_size": snapshot.sample_size,
        "prob_up_pct": snapshot.prob_up_pct,
        "prob_down_pct": snapshot.prob_down_pct,
        "prob_flat_pct": snapshot.prob_flat_pct,
        "avg_forward_return_pct": float(snapshot.avg_forward_return_pct),
        "computed_at": snapshot.computed_at.isoformat(),
    }
