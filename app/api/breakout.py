from fastapi import APIRouter, HTTPException, Query

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.analysis.regime import RegimeDetector
from app.services.breakout.engine import BreakoutEngine
from app.services.features.engine import FeatureEngine
from app.services.history.registry import find_symbol_config
from app.services.history.schemas import Timeframe
from app.services.market.repository import MarketRepository

router = APIRouter(prefix="/api/breakout", tags=["breakout"])


def _build_engine() -> BreakoutEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    return BreakoutEngine(
        session_factory,
        RegimeDetector(session_factory, market_repository),
        FeatureEngine(session_factory, market_repository),
    )


def _serialize(event) -> dict:
    return {
        "symbol": event.symbol,
        "timeframe": event.timeframe,
        "event_type": event.event_type,
        "direction": event.direction,
        "level": float(event.level),
        "price": float(event.price),
        "probability_pct": (
            float(event.probability_pct) if event.probability_pct is not None else None
        ),
        "confidence_pct": event.confidence_pct,
        "risk_score": float(event.risk_score) if event.risk_score is not None else None,
        "expected_continuation": event.expected_continuation,
        "reasoning": event.reasoning,
        "confirmations": {
            "volume": event.volume_confirmed,
            "atr": event.atr_confirmed,
            "vwap": event.vwap_confirmed,
            "regime": event.regime_confirmed,
            "oi_funding": event.oi_funding_confirmed,
            "multi_timeframe": event.multi_timeframe_confirmed,
        },
        "computed_at": event.computed_at.isoformat(),
    }


@router.get("/{symbol}")
async def get_breakout(
    symbol: str,
    timeframe: str = Query("1d", description="1d, 4h or 1h"),
    limit: int = Query(10, ge=1, le=100),
) -> dict:
    config = find_symbol_config(symbol)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Unknown historical symbol: {symbol}")

    try:
        tf = Timeframe(timeframe)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid timeframe: {timeframe}") from exc

    engine = _build_engine()
    await engine.compute_and_store(config.symbol, config.model, tf)
    events = await engine.get_recent(config.symbol, tf, limit=limit)

    return {
        "symbol": config.symbol,
        "timeframe": timeframe,
        "count": len(events),
        "events": [_serialize(e) for e in events],
    }
