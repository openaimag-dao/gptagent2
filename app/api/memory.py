from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from app.database.session import get_session_factory
from app.services.memory.engine import CATEGORY_NAMES, MemoryEngine

router = APIRouter(prefix="/api/memory", tags=["memory"])


def _build_engine() -> MemoryEngine:
    return MemoryEngine(get_session_factory())


@router.get("")
async def get_memory_timeline(
    category: str | None = Query(
        None, description=f"One of: {', '.join(CATEGORY_NAMES)}. Omit for every category."
    ),
    limit: int = Query(50, ge=1, le=200),
    since: datetime | None = Query(None, description="ISO 8601 timestamp lower bound"),
) -> dict:
    engine = _build_engine()
    if category is not None:
        if category not in CATEGORY_NAMES:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown category '{category}'. Valid: {', '.join(CATEGORY_NAMES)}",
            )
        entries = await engine.get_category(category, limit=limit, since=since)
    else:
        entries = await engine.get_timeline(limit=limit, since=since)
    return {"count": len(entries), "entries": entries, "categories": list(CATEGORY_NAMES)}
