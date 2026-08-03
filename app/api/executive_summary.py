from fastapi import APIRouter, HTTPException

from app.services.executive_summary.engine import build_executive_summary_engine

router = APIRouter(prefix="/api/executive-summary", tags=["executive-summary"])


@router.get("/{symbol}")
async def get_executive_summary(symbol: str) -> dict:
    engine = build_executive_summary_engine()
    payload = await engine.compute(symbol.upper())
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No executive summary available for {symbol.upper()} -- "
                "Market Watchdog hasn't completed a cycle yet."
            ),
        )
    return payload
