from fastapi import APIRouter, HTTPException, Query

from app.database.session import get_session_factory
from app.services.history.registry import find_symbol_config
from app.services.history.repository import get_recent_series
from app.services.history.schemas import Timeframe

router = APIRouter(prefix="/api/history", tags=["history"])


def _serialize_row(row) -> dict:
    return {
        "timestamp": row.timestamp.isoformat(),
        "open": float(row.open),
        "high": float(row.high),
        "low": float(row.low),
        "close": float(row.close),
        "volume": float(row.volume) if row.volume is not None else None,
        "return_pct": float(row.return_pct) if row.return_pct is not None else None,
        "volatility": float(row.volatility) if row.volatility is not None else None,
        "atr": float(row.atr) if row.atr is not None else None,
        "rsi": float(row.rsi) if row.rsi is not None else None,
        "macd": float(row.macd) if row.macd is not None else None,
        "macd_signal": float(row.macd_signal) if row.macd_signal is not None else None,
        "macd_histogram": float(row.macd_histogram) if row.macd_histogram is not None else None,
        "sma_20": float(row.sma_20) if row.sma_20 is not None else None,
        "sma_50": float(row.sma_50) if row.sma_50 is not None else None,
        "sma_200": float(row.sma_200) if row.sma_200 is not None else None,
        "volume_change_pct": (
            float(row.volume_change_pct) if row.volume_change_pct is not None else None
        ),
    }


@router.get("/{symbol}")
async def get_history(
    symbol: str,
    timeframe: str = Query("1d", description="4d, 1d, 4h, 1h, 30m, 15m or 5m"),
    limit: int = Query(100, ge=1, le=5000),
) -> dict:
    config = find_symbol_config(symbol)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Unknown historical symbol: {symbol}")

    try:
        tf = Timeframe(timeframe)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timeframe: {timeframe} (expected 4d, 1d, 4h, 1h, 30m, 15m or 5m)",
        ) from exc
    all_timeframes = (*config.timeframes, *config.realtime_timeframes)
    if tf not in all_timeframes:
        raise HTTPException(
            status_code=400,
            detail=f"{config.symbol} has no {timeframe} data (has: "
            f"{[t.value for t in all_timeframes]})",
        )

    rows = await get_recent_series(get_session_factory(), config.model, config.symbol, tf, limit)
    if not rows:
        raise HTTPException(
            status_code=404, detail=f"No history synced yet for {config.symbol}/{timeframe}"
        )

    return {
        "symbol": config.symbol,
        "timeframe": timeframe,
        "count": len(rows),
        "candles": [_serialize_row(row) for row in rows],
    }
