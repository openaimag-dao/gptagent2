"""v5.4 Next Generation Market Watchdog -- the central Market Monitoring
Hub API. Extends (does not replace) the existing Watchdog: alert history
is still the same AlertLog/MemoryEngine data every prior version served
(see WatchdogEngine.get_alert_history()), now embedded in one combined
dashboard payload alongside the new Current Market Status/Market Overview/
Crypto Overview/Macro Overview/OnChain Overview/AI Status/What Changed/
Provider Status sections.
"""

import os
import resource

from fastapi import APIRouter

from app.scheduler.jobs import (
    WATCHDOG_SNAPSHOT_JOB_ID,
    get_job_next_run,
    get_scheduled_job_count,
)
from app.services.watchdog.engine import build_watchdog_engine

router = APIRouter(prefix="/api/watchdog", tags=["watchdog"])


def _next_scan() -> str | None:
    next_run = get_job_next_run(WATCHDOG_SNAPSHOT_JOB_ID)
    return next_run.isoformat() if next_run is not None else None


@router.get("")
async def get_dashboard() -> dict:
    engine = build_watchdog_engine()
    dashboard = await engine.get_dashboard()
    dashboard["current_status"]["next_scan"] = _next_scan()
    return dashboard


@router.get("/events")
async def get_events(limit: int = 15) -> dict:
    engine = build_watchdog_engine()
    entries = await engine.get_alert_history(limit=limit)
    return {"count": len(entries), "entries": entries}


@router.get("/providers")
async def get_providers() -> dict:
    engine = build_watchdog_engine()
    return {"providers": await engine.get_provider_status()}


@router.get("/market")
async def get_market() -> dict:
    engine = build_watchdog_engine()
    return {
        "market_overview": await engine.get_market_overview(),
        "crypto_overview": await engine.get_crypto_overview(),
        "macro_overview": await engine.get_macro_overview(),
        "onchain_overview": await engine.get_onchain_overview(),
    }


@router.get("/ai")
async def get_ai_status() -> dict:
    engine = build_watchdog_engine()
    return await engine.get_ai_status()


@router.get("/brief")
async def get_market_brief() -> dict:
    """v8.0 "Market Control Center" -- direct verdicts (is the market
    healthy, is risk increasing, did AI change opinion, today's biggest
    changes, what needs attention now), composed from the same sections
    /ai and /changes already serve."""
    engine = build_watchdog_engine()
    return await engine.get_market_brief()


@router.get("/changes")
async def get_changes() -> dict:
    engine = build_watchdog_engine()
    return await engine.get_what_changed()


@router.get("/performance")
async def get_performance() -> dict:
    engine = build_watchdog_engine()
    status = await engine.get_current_status()
    usage = resource.getrusage(resource.RUSAGE_SELF)
    try:
        load_avg = os.getloadavg()
    except (AttributeError, OSError):
        # getloadavg() is POSIX-only -- honestly unavailable rather than faked.
        load_avg = None
    return {
        "scan_duration_ms": status["scan_duration_ms"],
        "last_update": status["last_update"],
        "next_scan": _next_scan(),
        # ru_maxrss is KB on Linux (where this runs in production).
        "memory_mb": round(usage.ru_maxrss / 1024, 1),
        "cpu_load_avg": load_avg,
        "scheduled_job_count": get_scheduled_job_count(),
    }
