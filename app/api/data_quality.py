from fastapi import APIRouter

from app.database.session import get_session_factory
from app.services.data_quality.engine import DataQualityEngine

router = APIRouter(prefix="/api/data-quality", tags=["brain"])


def _serialize(result: dict) -> dict:
    return {
        **result,
        "most_recent_timestamp": (
            result["most_recent_timestamp"].isoformat()
            if result["most_recent_timestamp"] is not None
            else None
        ),
    }


@router.get("")
async def get_data_quality_report() -> dict:
    engine = DataQualityEngine(get_session_factory())
    report = await engine.assess_all()
    return {**report, "results": [_serialize(r) for r in report["results"]]}
