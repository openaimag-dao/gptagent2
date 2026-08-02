from fastapi import APIRouter, HTTPException

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.analysis.correlation import CorrelationEngine
from app.services.analysis.regime import RegimeDetector
from app.services.analysis.report import ReportGenerator, build_institutional_report
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.scanner.engine import build_market_scanner_engine
from app.services.signals.engine import SignalEngine

router = APIRouter(prefix="/api/report", tags=["report"])


def build_report_generator() -> ReportGenerator:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    return ReportGenerator(
        session_factory=session_factory,
        market_repository=market_repository,
        news_repository=NewsRepository(session_factory),
        correlation_engine=CorrelationEngine(session_factory),
        regime_detector=RegimeDetector(session_factory, market_repository),
        signal_engine=SignalEngine(
            session_factory, market_repository, NewsRepository(session_factory)
        ),
    )


async def _serialize(report) -> dict:
    sector_breadth = await build_market_scanner_engine().get_latest_sector_breadth()
    return {
        "id": str(report.id),
        "report_type": report.report_type,
        "regime": report.regime,
        "risk_level": report.risk_level,
        "bull_score": report.bull_score,
        "bear_score": report.bear_score,
        "confidence_pct": report.confidence_pct,
        "market_summary": report.market_summary,
        "correlations_summary": report.correlations_summary,
        "institutional_summary": report.institutional_summary,
        "institutional_report": build_institutional_report(report, sector_breadth),
        "analysis": report.analysis,
        "generated_at": report.generated_at.isoformat(),
    }


@router.get("")
async def get_latest_report() -> dict:
    generator = build_report_generator()
    report = await generator.get_latest()
    if report is None:
        raise HTTPException(status_code=404, detail="No report has been generated yet")
    return await _serialize(report)


@router.post("/generate")
async def generate_report() -> dict:
    """Generates a fresh report on demand (in addition to the scheduled cadence)."""
    generator = build_report_generator()
    try:
        report = await generator.generate_and_store(report_type="on_demand")
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return await _serialize(report)
