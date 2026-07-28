from fastapi import APIRouter, Query

from app.services.shocks.engine import build_critical_alert_engine

router = APIRouter(prefix="/api/shocks", tags=["shocks"])


def _serialize(row) -> dict:
    return {
        "id": row.id,
        "alert_key": row.alert_key,
        "category": row.category,
        "tier": row.tier,
        "symbols": row.symbols,
        "message": row.message,
        "active": row.active,
        "first_triggered_at": row.first_triggered_at.isoformat(),
        "last_updated_at": row.last_updated_at.isoformat(),
        "resolved_at": row.resolved_at.isoformat() if row.resolved_at is not None else None,
    }


@router.get("/active")
async def get_active() -> dict:
    engine = build_critical_alert_engine()
    rows = await engine.list_active()
    return {"active": [_serialize(r) for r in rows]}


@router.get("/history")
async def get_history(limit: int = Query(20, ge=1, le=200)) -> dict:
    engine = build_critical_alert_engine()
    rows = await engine.list_history(limit)
    return {"history": [_serialize(r) for r in rows]}
