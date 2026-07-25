from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database.session import get_session_factory
from app.services.backtest.conditions import Condition
from app.services.backtest.engine import BacktestEngine
from app.services.history.schemas import Timeframe

router = APIRouter(prefix="/api/backtest", tags=["brain"])


class ConditionRequest(BaseModel):
    symbol: str
    field: str
    operator: str
    value: float


class BacktestRequest(BaseModel):
    target_symbol: str
    conditions: list[ConditionRequest] = Field(min_length=1)
    timeframe: str = "1d"
    horizon: int = Field(default=1, ge=1)


@router.post("")
async def run_backtest(request: BacktestRequest) -> dict:
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

    engine = BacktestEngine(get_session_factory())
    result = await engine.run(
        conditions, request.target_symbol.upper(), timeframe, request.horizon
    )
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="No historical occurrences of this rule found -- check the symbols "
            "have synced history and the conditions ever actually co-occur",
        )
    return result
