import asyncio
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Query

from app.database.session import get_session_factory
from app.services.calendar.engine import EconomicCalendarEngine
from app.services.history.events import seed_events
from app.services.history.pipeline import run_sync, run_validation
from app.services.history.registry import build_registry

router = APIRouter(prefix="/api/admin", tags=["admin"])
logger = logging.getLogger(__name__)

_status: dict = {"state": "idle", "started_at": None, "finished_at": None, "error": None}


async def _run_history_sync(years: int) -> None:
    session_factory = get_session_factory()
    registry = build_registry()
    try:
        await run_sync(session_factory, registry, years)
        await run_validation(session_factory, registry, repair=True)

        calendar_engine = EconomicCalendarEngine(session_factory)
        await calendar_engine.sync_fred_releases()
        await calendar_engine.seed_central_bank_meetings()
        await seed_events(session_factory)

        _status["state"] = "done"
        logger.info("Admin-triggered history sync complete")
    except Exception as exc:
        _status["state"] = "failed"
        _status["error"] = str(exc)
        logger.exception("Admin-triggered history sync failed")
    finally:
        _status["finished_at"] = datetime.now(UTC).isoformat()


@router.post("/sync-history")
async def trigger_history_sync(years: int = Query(default=10, ge=1, le=15)) -> dict:
    """Runs the same pipeline as `python sync_history.py` (full OHLCV sync +
    validation/repair, curated events seed, economic calendar sync) in the
    background against this deployment's own database.

    Exists because the Historical Intelligence tables can only be backfilled
    from inside this service's network (the database has no public access) --
    this lets that be triggered over HTTP instead of requiring shell access
    to the running container.
    """
    if _status["state"] == "running":
        return dict(_status)

    _status.update(state="running", started_at=datetime.now(UTC).isoformat(), error=None)
    asyncio.create_task(_run_history_sync(years))
    return dict(_status)


@router.get("/sync-history")
async def get_history_sync_status() -> dict:
    return dict(_status)
