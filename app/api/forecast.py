from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.scheduler.jobs import FORECAST_JOB_ID, get_job_next_run
from app.services.explainability.engine import build_explainability_engine
from app.services.forecast.engine import HORIZONS, build_forecast_engine
from app.services.realtime.config import parse_watchlist

router = APIRouter(prefix="/api/forecast", tags=["forecast"])


def _official_forecast_symbols() -> tuple[str, ...]:
    return tuple(parse_watchlist(get_settings().official_forecast_symbols))


def _serialize_official(row) -> dict:
    return {
        "symbol": row.symbol,
        "available": True,
        "current_price": float(row.current_price),
        "target_price": float(row.target_price),
        "expected_change_pct": float(row.expected_change_pct),
        "direction": row.direction,
        "probability_pct": row.probability_pct,
        "confidence_tier": row.confidence_tier,
        "regime_at_forecast": row.regime_at_forecast,
        "official_forecast_date": row.official_forecast_date.isoformat()
        if row.official_forecast_date is not None
        else None,
        "computed_at": row.computed_at.isoformat(),
        "forecast_status": row.forecast_status,
        "realized_price": float(row.realized_price) if row.realized_price is not None else None,
        "error_pct": float(row.error_pct) if row.error_pct is not None else None,
        "direction_correct": row.direction_correct,
        "target_reached": row.target_reached,
        "max_favorable_excursion_pct": float(row.max_favorable_excursion_pct)
        if row.max_favorable_excursion_pct is not None
        else None,
        "max_adverse_excursion_pct": float(row.max_adverse_excursion_pct)
        if row.max_adverse_excursion_pct is not None
        else None,
        "error_type": row.error_type,
        "evaluated_at": row.evaluated_at.isoformat() if row.evaluated_at is not None else None,
    }


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

    # AI Explanation: every contributing engine's Signal/Weight/Confidence/
    # Reason, built by ExplainabilityEngine's own "Why AI Thinks This"
    # composer (app/services/explainability/engine.py) -- called here at
    # the API layer, not from ForecastEngine itself, since
    # ExplainabilityEngine already imports from forecast.engine and a
    # reverse import would create a cycle. No new computation: this reuses
    # the exact same engine_breakdown/final_prediction the "Why AI Thinks
    # This" page already shows.
    explainability = await build_explainability_engine().build(symbol.upper())
    payload["ai_explanation"] = {
        "engine_breakdown": explainability["engine_breakdown"],
        "final_prediction": explainability["final_prediction"],
    }

    # Forecast Intelligence Upgrade: does this horizon's own call agree
    # with the other horizons already computed for this symbol? Reads
    # already-stored snapshots (see get_horizon_consistency), no extra
    # forecast computation.
    payload["horizon_consistency"] = await engine.get_horizon_consistency(symbol.upper())
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
                "forecast_version": s.forecast_version,
                "forecast_status": s.forecast_status,
                "invalidation_reason": s.invalidation_reason,
                "invalidated_at": s.invalidated_at.isoformat()
                if s.invalidated_at is not None
                else None,
            }
            for s in snapshots
        ],
    }


@router.get("/official/daily")
async def get_official_daily_forecasts() -> dict:
    """Forecasting 2.0 (Part 34 Page 1) -- today's (UTC) one official 24h
    forecast per asset in official_forecast_symbols (BTC/SOL/LINK/UNI by
    default). A symbol with no row for today (insufficient data, or the
    daily job hasn't fired yet) is reported as `available: false`, never
    a fabricated forecast."""
    engine = build_forecast_engine()
    symbols = _official_forecast_symbols()
    by_symbol = await engine.get_official_daily(symbols)
    return {
        "date": datetime.now(UTC).date().isoformat(),
        "forecasts": [
            _serialize_official(by_symbol[symbol])
            if symbol in by_symbol
            else {"symbol": symbol, "available": False}
            for symbol in symbols
        ],
    }


@router.get("/{symbol}/official/history")
async def get_official_forecast_history(symbol: str, limit: int = Query(30, le=100)) -> dict:
    """Forecasting 2.0 (Part 34 Page 2/3) -- past official daily 24h
    forecasts for one symbol, most recent first, with graded outcomes
    where available."""
    symbol = symbol.upper()
    engine = build_forecast_engine()
    rows = await engine.get_official_history(symbol, limit)
    return {"symbol": symbol, "forecasts": [_serialize_official(r) for r in rows]}
