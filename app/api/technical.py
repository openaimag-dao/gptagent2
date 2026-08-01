from fastapi import APIRouter, HTTPException

from app.services.technical.engine import build_technical_analysis_engine

router = APIRouter(prefix="/api/technical", tags=["technical"])


def _serialize(snapshot) -> dict:
    return {
        "symbol": snapshot.symbol,
        "source": snapshot.source,
        "bullish_score": float(snapshot.bullish_score)
        if snapshot.bullish_score is not None
        else None,
        "bearish_score": float(snapshot.bearish_score)
        if snapshot.bearish_score is not None
        else None,
        "trend_strength": float(snapshot.trend_strength)
        if snapshot.trend_strength is not None
        else None,
        "momentum": float(snapshot.momentum) if snapshot.momentum is not None else None,
        "volatility": float(snapshot.volatility) if snapshot.volatility is not None else None,
        "breakout_probability": (
            float(snapshot.breakout_probability)
            if snapshot.breakout_probability is not None
            else None
        ),
        "breakdown_probability": (
            float(snapshot.breakdown_probability)
            if snapshot.breakdown_probability is not None
            else None
        ),
        "confidence": float(snapshot.confidence) if snapshot.confidence is not None else None,
        "active_signals": snapshot.active_signals,
        "timeframes_covered": snapshot.timeframes_covered,
        "support": float(snapshot.support) if snapshot.support is not None else None,
        "resistance": float(snapshot.resistance) if snapshot.resistance is not None else None,
        "computed_at": snapshot.computed_at.isoformat(),
    }


@router.get("/{symbol}")
async def get_technical(symbol: str) -> dict:
    """The AI-interpreted technical read for a symbol -- bullish/bearish
    score, trend strength, momentum, volatility, breakout/breakdown
    probability, confidence and active signal names. Raw indicator values
    (RSI, MACD, ...) are never exposed here -- see
    app.services.technical.engine's module docstring."""
    engine = build_technical_analysis_engine()
    snapshot = await engine.get_latest(symbol)
    if snapshot is not None:
        return _serialize(snapshot)

    result = await engine.analyze(symbol)
    if result is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No technical analysis available for {symbol} -- not in the synced history "
                "registry and TradingView MCP is not configured"
            ),
        )
    return result
