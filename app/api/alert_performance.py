from fastapi import APIRouter, Query

from app.database.session import get_session_factory
from app.services.alert_performance.engine import (
    summarize_alert_performance,
    summarize_alert_performance_by_type,
)

router = APIRouter(prefix="/api/alert-performance", tags=["alert-performance"])


@router.get("")
async def get_alert_performance(alert_type: str | None = Query(None)) -> dict:
    return await summarize_alert_performance(get_session_factory(), alert_type=alert_type)


@router.get("/by-type")
async def get_alert_performance_by_type() -> list[dict]:
    return await summarize_alert_performance_by_type(get_session_factory())
