"""AI Brain Engine -- the institutional-grade synthesis of every other engine's
output into one narrative report. This is deliberately a thin alias over
`ReportGenerator` (see app/api/reports.py), not a second implementation:
the "brain" is the same report, just named for what it is."""

from fastapi import APIRouter, Depends, HTTPException

from app.api.admin import require_admin_key
from app.api.reports import _serialize, build_report_generator

router = APIRouter(prefix="/api/brain", tags=["brain"])


@router.get("")
async def get_latest_brain_report() -> dict:
    generator = build_report_generator()
    report = await generator.get_latest()
    if report is None:
        raise HTTPException(status_code=404, detail="No report has been generated yet")
    return await _serialize(report)


@router.post("/generate", dependencies=[Depends(require_admin_key)])
async def generate_brain_report() -> dict:
    generator = build_report_generator()
    try:
        report = await generator.generate_and_store(report_type="brain_on_demand")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return await _serialize(report)
