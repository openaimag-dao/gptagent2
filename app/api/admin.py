import asyncio
import hmac
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query

from app.config import get_settings
from app.database.session import get_session_factory
from app.services.calendar.engine import EconomicCalendarEngine
from app.services.history.events import seed_events
from app.services.history.pipeline import run_sync, run_validation
from app.services.history.registry import build_registry

logger = logging.getLogger(__name__)


async def require_admin_key(x_admin_key: str | None = Header(default=None)) -> None:
    """Every route on this router runs an alembic migration or triggers a
    multi-year external-API backfill, and this router has no other access
    control -- the database itself has no public access, so these
    endpoints exist specifically to be reachable from this deployment's
    public URL. ADMIN_API_KEY unset means "reject every request", never
    "allow every request": there is no way to leave this open by
    forgetting to configure it."""
    settings = get_settings()
    if (
        not settings.admin_api_key
        or not x_admin_key
        or not hmac.compare_digest(x_admin_key, settings.admin_api_key)
    ):
        raise HTTPException(status_code=401, detail="Missing or invalid X-Admin-Key header")


router = APIRouter(prefix="/api/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])

_REPO_ROOT = Path(__file__).resolve().parents[2]

_status: dict = {"state": "idle", "started_at": None, "finished_at": None, "error": None}


async def _run_history_sync(years: int) -> None:
    session_factory = get_session_factory()
    registry = build_registry()
    try:
        await run_sync(session_factory, registry, years)
        await run_validation(session_factory, registry, repair=True)

        # Best-effort: the calendar sync hits the same external (rate-limited)
        # APIs as the OHLCV backfill above, so a failure here shouldn't erase
        # a sync that otherwise completed.
        try:
            calendar_engine = EconomicCalendarEngine(session_factory)
            await calendar_engine.sync_fred_releases()
            await calendar_engine.seed_central_bank_meetings()
        except Exception:
            logger.warning("Admin-triggered history sync: calendar sync failed", exc_info=True)

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


@router.post("/migrate")
async def trigger_migration() -> dict:
    """Runs `alembic upgrade head` against this deployment's own database.

    Exists for the same reason as /sync-history above: this database has no
    public access, so a migration written from outside the running
    container's network can only be applied by asking the container itself
    to run it, over HTTP, instead of requiring shell access.
    """
    proc = await asyncio.create_subprocess_exec(
        "alembic",
        "upgrade",
        "head",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=_REPO_ROOT,
    )
    stdout, _ = await proc.communicate()
    output = stdout.decode(errors="replace")
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=output[-4000:])
    return {"status": "ok", "output": output[-4000:]}
