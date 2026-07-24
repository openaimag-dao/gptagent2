from fastapi import APIRouter

from app.database.session import get_session_factory
from app.services.analysis.correlation import CorrelationEngine

router = APIRouter(prefix="/api/correlations", tags=["correlations"])


@router.get("")
async def get_latest_correlations() -> dict:
    engine = CorrelationEngine(get_session_factory())
    rows = await engine.get_latest()

    return {
        "count": len(rows),
        "correlations": [
            {
                "symbol_a": row.symbol_a,
                "symbol_b": row.symbol_b,
                "window_days": row.window_days,
                "correlation": float(row.correlation),
                "data_points": row.data_points,
                "calculated_at": row.calculated_at.isoformat(),
            }
            for row in rows
        ],
    }
