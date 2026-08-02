from fastapi import APIRouter, HTTPException, Query

from app.database.session import get_session_factory
from app.services.history.registry import find_symbol_config
from app.services.history.schemas import Timeframe
from app.services.similar_market.engine import SimilarMarketEngine, build_historical_lesson

router = APIRouter(prefix="/api/similar", tags=["brain"])


@router.get("/{symbol}")
async def get_similar_periods(
    symbol: str,
    timeframe: str = Query("1d", description="1d, 4h or 1h"),
    k: int = Query(25, ge=1, le=50),
) -> dict:
    config = find_symbol_config(symbol)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Unknown historical symbol: {symbol}")

    try:
        tf = Timeframe(timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {timeframe}") from exc
    if tf not in config.timeframes:
        raise HTTPException(status_code=400, detail=f"{config.symbol} has no {timeframe} data")

    engine = SimilarMarketEngine(get_session_factory())
    matches = await engine.find_and_store(config.symbol, config.model, tf, k=k)
    if not matches:
        raise HTTPException(
            status_code=404,
            detail=f"Not enough synced history for {config.symbol}/{timeframe} to find "
            "similar periods yet -- run sync_history.py first",
        )

    return {
        "symbol": config.symbol,
        "timeframe": timeframe,
        "count": len(matches),
        "lesson": build_historical_lesson(config.symbol, matches),
        "matches": [
            {
                "date": m["date"].isoformat(),
                "similarity": m["similarity"],
                "market_regime": m["market_regime"],
                "rsi": m["rsi"],
                "volatility": m["volatility"],
                "btc_result_pct": m["btc_result_pct"],
                "nasdaq_result_pct": m["nasdaq_result_pct"],
                "forward_returns_pct": m["forward_returns_pct"],
            }
            for m in matches
        ],
    }
