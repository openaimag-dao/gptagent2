from fastapi import APIRouter, HTTPException, Query

from app.database.session import get_session_factory
from app.services.forecast.engine import HORIZONS
from app.services.trade_setup.engine import evaluate_trade_setup_for_symbol

router = APIRouter(prefix="/api/trade-setup", tags=["trade-setup"])


@router.get("/{symbol}")
async def get_trade_setup(symbol: str, horizon: str = Query("24h")) -> dict:
    if horizon not in HORIZONS:
        raise HTTPException(status_code=400, detail=f"horizon must be one of {sorted(HORIZONS)}")
    result = await evaluate_trade_setup_for_symbol(get_session_factory(), symbol.upper(), horizon)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No forecast available for {symbol.upper()} -- "
                "insufficient history/probability data."
            ),
        )
    return result
