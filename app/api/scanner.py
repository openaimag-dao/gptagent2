"""v5.5 Market Scanner API -- current scans, latest detections, top
movers, sector leaders, pending/suppressed alerts. Read-only: the scanner
itself only ever writes via its own scheduled cycle
(compute_market_scan_job); nothing here triggers a fresh CoinGecko fetch.
"""

from fastapi import APIRouter, Query

from app.services.scanner.engine import build_market_scanner_engine

router = APIRouter(prefix="/api/scanner", tags=["scanner"])


def _serialize_snapshot(row) -> dict:
    return {
        "symbol": row.symbol,
        "name": row.name,
        "price": float(row.price),
        "change_pct_1h": float(row.change_pct_1h) if row.change_pct_1h is not None else None,
        "change_pct_24h": float(row.change_pct_24h) if row.change_pct_24h is not None else None,
        "volume_24h": float(row.volume_24h) if row.volume_24h is not None else None,
        "market_cap": float(row.market_cap) if row.market_cap is not None else None,
        "market_cap_rank": row.market_cap_rank,
        "sector": row.sector,
        "recorded_at": row.recorded_at.isoformat(),
    }


def _serialize_alert(row) -> dict:
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


def _serialize_log(row) -> dict:
    return {
        "id": row.id,
        "alert_type": row.alert_type,
        "message": row.message,
        "conviction_tier": row.conviction_tier,
        "confidence_pct": row.confidence_pct,
        "triggered_at": row.triggered_at.isoformat(),
    }


@router.get("")
async def get_dashboard() -> dict:
    engine = build_market_scanner_engine()
    snapshots = await engine.get_latest_snapshots(limit=100)
    recent_alerts = await engine.list_recent_alerts(limit=50)
    pending = await engine.list_active_alerts()
    suppressed = await engine.list_suppressed_alerts(limit=50)
    breadth = await engine.get_latest_breadth()
    sector_breadth = await engine.get_latest_sector_breadth()
    # Composed from the same WatchdogSnapshot the scanner's own AI filter
    # already reads every cycle (regime/risk/confidence/committee/consensus
    # plus Scenario Engine's expected_scenario/highest_risk/
    # biggest_opportunity) -- a cheap cached-row read, not a fresh
    # agent-orchestrator run, so this was previously only ever visible
    # inside a fired HIGH/CRITICAL Telegram alert and never on the
    # dashboard itself.
    market_context = await engine.get_market_context()
    return {
        "current_scans": [_serialize_snapshot(s) for s in snapshots],
        "latest_detections": [_serialize_alert(a) for a in recent_alerts],
        "top_movers": breadth,
        "sector_leaders": sector_breadth,
        "pending_alerts": [_serialize_alert(a) for a in pending],
        "suppressed_alerts": [_serialize_log(a) for a in suppressed],
        "market_context": market_context,
    }


@router.get("/scans")
async def get_current_scans(limit: int = Query(100, ge=1, le=500)) -> dict:
    engine = build_market_scanner_engine()
    snapshots = await engine.get_latest_snapshots(limit=limit)
    return {"scans": [_serialize_snapshot(s) for s in snapshots]}


@router.get("/detections")
async def get_latest_detections(limit: int = Query(50, ge=1, le=200)) -> dict:
    engine = build_market_scanner_engine()
    alerts = await engine.list_recent_alerts(limit=limit)
    return {"detections": [_serialize_alert(a) for a in alerts]}


@router.get("/movers")
async def get_top_movers() -> dict:
    engine = build_market_scanner_engine()
    breadth = await engine.get_latest_breadth()
    return breadth or {
        "total_scanned": 0,
        "rising_count": 0,
        "falling_count": 0,
        "unchanged_count": 0,
        "top_gainers": [],
        "top_losers": [],
        "top_volume_increase": [],
    }


@router.get("/sectors")
async def get_sector_leaders() -> dict:
    engine = build_market_scanner_engine()
    return {"sectors": await engine.get_latest_sector_breadth()}


@router.get("/pending")
async def get_pending_alerts() -> dict:
    engine = build_market_scanner_engine()
    pending = await engine.list_active_alerts()
    return {"pending": [_serialize_alert(a) for a in pending]}


@router.get("/suppressed")
async def get_suppressed_alerts(limit: int = Query(50, ge=1, le=200)) -> dict:
    engine = build_market_scanner_engine()
    suppressed = await engine.list_suppressed_alerts(limit=limit)
    return {"suppressed": [_serialize_log(a) for a in suppressed]}
