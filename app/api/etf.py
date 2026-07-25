from fastapi import APIRouter, Query

from app.database.session import get_session_factory
from app.services.etf.engine import ETFIntelligenceEngine
from app.services.news.repository import NewsRepository

router = APIRouter(prefix="/api/etf", tags=["brain"])


@router.get("")
async def get_etf_flow_proxy(window_hours: int = Query(72, ge=1, le=24 * 30)) -> dict:
    engine = ETFIntelligenceEngine(NewsRepository(get_session_factory()))
    return await engine.get_flow_proxy(window_hours=window_hours)
