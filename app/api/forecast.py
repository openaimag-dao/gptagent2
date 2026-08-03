from fastapi import APIRouter, HTTPException, Query

from app.scheduler.jobs import FORECAST_JOB_ID, get_job_next_run
from app.services.forecast.engine import HORIZONS, build_forecast_engine

router = APIRouter(prefix="/api/forecast", tags=["forecast"])


def _next_refresh() -> str | None:
    next_run = get_job_next_run(FORECAST_JOB_ID)
    return next_run.isoformat() if next_run is not None else None


@router.get("/{symbol}")
async def get_forecast(symbol: str, horizon: str = Query("24h")) -> dict:
    if horizon not in HORIZONS:
        raise HTTPException(status_code=400, detail=f"horizon must be one of {sorted(HORIZONS)}")
    engine = build_forecast_engine()
    payload = await engine.compute(symbol.upper(), horizon)
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No forecast available for {symbol.upper()} -- "
                "insufficient history/probability data."
            ),
        )
    payload["next_refresh_at"] = _next_refresh()
    return payload


@router.get("/{symbol}/history")
async def get_forecast_history(symbol: str, limit: int = Query(20, le=100)) -> dict:
    symbol = symbol.upper()
    engine = build_forecast_engine()
    snapshots = await engine.get_latest_history(symbol, limit)

    accuracy_by_horizon = {}
    for horizon in HORIZONS:
        summary = await engine.summarize_accuracy(symbol, horizon)
        accuracy_by_horizon[horizon] = summary or {"evaluated_count": 0, "avg_abs_error_pct": None}

    return {
        "symbol": symbol,
        "accuracy_by_horizon": accuracy_by_horizon,
        "forecasts": [
            {
                "horizon": s.horizon,
                "computed_at": s.computed_at.isoformat(),
                "current_price": float(s.current_price),
                "target_price": float(s.target_price),
                "direction": s.direction,
                "probability_pct": s.probability_pct,
                "confidence_tier": s.confidence_tier,
                "realized_price": float(s.realized_price) if s.realized_price is not None else None,
                "error_pct": float(s.error_pct) if s.error_pct is not None else None,
                "evaluated_at": s.evaluated_at.isoformat() if s.evaluated_at is not None else None,
            }
            for s in snapshots
        ],
    }
