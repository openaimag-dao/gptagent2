from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database.session import get_session_factory
from app.services.backtest.conditions import Condition
from app.services.backtest.strategy_engine import StrategyLabEngine
from app.services.history.schemas import Timeframe

router = APIRouter(prefix="/api/strategy", tags=["brain"])


class ConditionRequest(BaseModel):
    symbol: str
    field: str
    operator: str
    value: float


class StrategyRequest(BaseModel):
    target_symbol: str
    conditions: list[ConditionRequest] = Field(min_length=1)
    timeframe: str = "1d"
    horizon: int = Field(default=1, ge=1)
    stop_loss_pct: float | None = Field(default=None, gt=0)
    take_profit_pct: float | None = Field(default=None, gt=0)
    position_size_pct: float = Field(default=1.0, gt=0, le=1.0)
    mode: Literal["run", "walk_forward", "monte_carlo"] = "run"
    folds: int = Field(default=4, ge=2, le=12)
    n_simulations: int = Field(default=1000, ge=100, le=10000)


@router.post("")
async def run_strategy(request: StrategyRequest) -> dict:
    try:
        timeframe = Timeframe(request.timeframe)
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail=f"Invalid timeframe: {request.timeframe}"
        ) from exc

    try:
        conditions = [
            Condition(symbol=c.symbol.upper(), field=c.field, operator=c.operator, value=c.value)
            for c in request.conditions
        ]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    engine = StrategyLabEngine(get_session_factory())
    common_kwargs = dict(
        conditions=conditions,
        target_symbol=request.target_symbol.upper(),
        timeframe=timeframe,
        horizon=request.horizon,
        stop_loss_pct=request.stop_loss_pct,
        take_profit_pct=request.take_profit_pct,
        position_size_pct=request.position_size_pct,
    )

    if request.mode == "walk_forward":
        result = await engine.walk_forward(**common_kwargs, folds=request.folds)
        if not result:
            raise HTTPException(
                status_code=404, detail="Not enough stored history for this many folds"
            )
        return {"folds": result}

    if request.mode == "monte_carlo":
        result = await engine.monte_carlo(**common_kwargs, n_simulations=request.n_simulations)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail="No historical occurrences of this rule found (need at least 2 "
                "trades to resample)",
            )
        return result

    result = await engine.run(**common_kwargs)
    if result is None:
        raise HTTPException(status_code=404, detail="No historical occurrences of this rule found")
    return result
