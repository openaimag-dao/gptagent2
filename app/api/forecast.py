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
        "id": row.id,
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


def _serialize_official_detail(row) -> dict:
    """Page 3 (Forecast Details): every field `_serialize_official`
    exposes plus the full input snapshot and lineage a drill-down needs --
    checkpoints/distribution/key_levels (the actual model output that
    produced target_price/direction), reference_timestamp (which history
    candle this was computed from), forecast_version/model_version/
    invalidation fields (is this still the live call for its day, or
    superseded, and which revision of the forecast formula produced it --
    see FORECAST_MODEL_VERSION's own docstring), and the two baseline
    comparisons already graded alongside it."""
    payload = _serialize_official(row)
    payload.update(
        {
            "checkpoints": row.checkpoints,
            "distribution": row.distribution,
            "key_levels": row.key_levels,
            "reference_timestamp": row.reference_timestamp.isoformat()
            if row.reference_timestamp is not None
            else None,
            "forecast_version": row.forecast_version,
            "model_version": row.model_version,
            "invalidation_reason": row.invalidation_reason,
            "invalidated_at": row.invalidated_at.isoformat()
            if row.invalidated_at is not None
            else None,
            "momentum_baseline_correct": row.momentum_baseline_correct,
            "historical_mean_baseline_error_pct": float(row.historical_mean_baseline_error_pct)
            if row.historical_mean_baseline_error_pct is not None
            else None,
        }
    )
    return payload


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


@router.get("/official/agent-performance")
async def get_agent_performance() -> dict:
    """Forecasting 2.0 (Part 26 / Page 5) -- per (agent, symbol) direction
    accuracy across graded official daily forecasts, for
    official_forecast_symbols. A group with too few graded observations
    reports `accuracy_pct: null, insufficient_sample: true` instead of an
    unreliable percentage."""
    engine = build_forecast_engine()
    rows = await engine.get_agent_performance(_official_forecast_symbols())
    return {"min_sample_size": get_settings().agent_performance_min_sample_size, "rows": rows}


@router.get("/official/performance")
async def get_official_performance() -> dict:
    """Forecasting 2.0 (Page 4, Performance) -- the overall scorecard
    across every graded official daily forecast in official_forecast_symbols:
    summary stats, a probability-calibration curve, and accuracy broken
    down by regime. Distinct from /official/agent-performance (per-agent)
    and /official/learning-center (needs two regimes per agent)."""
    engine = build_forecast_engine()
    return await engine.get_official_performance(_official_forecast_symbols())


@router.get("/official/error-lab")
async def get_error_lab(limit: int = Query(20, le=100)) -> dict:
    """Forecasting 2.0 (Part 27/28 / Page 6) -- the most recent official
    daily forecasts that graded WRONG, most recent first, each with its
    linked per-agent evidence."""
    engine = build_forecast_engine()
    entries = await engine.get_error_lab(_official_forecast_symbols(), limit)
    return {
        "entries": [
            {
                "forecast": _serialize_official(entry["forecast"]),
                "agents": [
                    {
                        "agent_name": a.agent_name,
                        "direction": a.direction,
                        "confidence_pct": a.confidence_pct,
                    }
                    for a in entry["agents"]
                ],
            }
            for entry in entries
        ]
    }


@router.get("/official/detail/{forecast_id}")
async def get_forecast_detail(forecast_id: int) -> dict:
    """Forecasting 2.0 (Page 3, Forecast Details): full input snapshot and
    complete per-agent evidence for one official daily forecast. 404 when
    forecast_id doesn't match an official daily row -- never a fabricated
    detail page for an id that doesn't exist or isn't official."""
    engine = build_forecast_engine()
    detail = await engine.get_forecast_detail(forecast_id)
    if detail is None:
        raise HTTPException(
            status_code=404,
            detail=f"No official daily forecast with id {forecast_id}.",
        )
    return {
        "forecast": _serialize_official_detail(detail["forecast"]),
        "agents": [
            {
                "agent_name": a.agent_name,
                "direction": a.direction,
                "confidence_pct": a.confidence_pct,
                "key_factors": a.key_factors,
            }
            for a in detail["agents"]
        ],
    }


@router.get("/official/learning-center")
async def get_learning_center() -> dict:
    """Forecasting 2.0 (Part 33 / Page 7, Learning Center) -- regime-
    conditioned accuracy comparisons per (agent, symbol), grouped by
    symbol for display. Empty for a symbol/agent pair until enough graded
    forecasts exist in at least two distinct regimes -- see
    derive_learning_insights's own docstring for the exact sample-size and
    gap-size gates that keep this from ever guessing an insight."""
    engine = build_forecast_engine()
    settings = get_settings()
    insights = await engine.get_learning_insights(_official_forecast_symbols())
    by_symbol: dict[str, list[dict]] = {}
    for insight in insights:
        by_symbol.setdefault(insight["symbol"], []).append(insight)
    return {
        "min_sample_size": settings.learning_insight_min_sample_size,
        "min_gap_pct": settings.learning_insight_min_gap_pct,
        "by_symbol": by_symbol,
    }
