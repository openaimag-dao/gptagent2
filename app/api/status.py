from fastapi import APIRouter

from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.scheduler.jobs import (
    compute_forecast_job,
    generate_official_daily_forecast_job,
    get_job_run_status,
    grade_forecasts_job,
    official_forecast_symbols,
)
from app.services.analysis.regime import RegimeDetector
from app.services.forecast.engine import build_forecast_engine
from app.services.global_score.engine import GlobalScoreEngine
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.signals.engine import SignalEngine

router = APIRouter(prefix="/api/status", tags=["status"])


def _job_status_block(job_func) -> dict:
    status = get_job_run_status(job_func.__name__) or {}
    return {
        "last_run_at": _iso(status.get("last_run_at")),
        "last_success_at": _iso(status.get("last_success_at")),
        "last_failure_at": _iso(status.get("last_failure_at")),
        "last_failure_error": status.get("last_failure_error"),
    }


def _iso(value) -> str | None:
    return value.isoformat() if value is not None else None


@router.get("")
async def get_status() -> dict:
    """Last-computed timestamps for the core engines, so staleness is
    visible rather than guessed -- same data /status in Telegram reports.
    Also the official-forecast pipeline's operational health (Forecasting
    3.0 Phase 29): per-job last-run/success/failure (see
    scheduler.jobs.get_job_run_status for what "failure" can and can't
    catch) plus real queried signals -- when a prediction was last
    actually persisted, how many are still waiting to be graded, and how
    many of today's official forecasts have already gone stale."""
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )

    signal_snapshot = await signal_engine.get_latest()
    regime_snapshot = await regime_detector.get_latest()
    global_score = await global_score_engine.get_latest()
    forecast_health = await build_forecast_engine().get_operational_health(
        official_forecast_symbols()
    )

    return {
        "signal_computed_at": (
            signal_snapshot.computed_at.isoformat() if signal_snapshot is not None else None
        ),
        "regime_computed_at": (
            regime_snapshot.computed_at.isoformat() if regime_snapshot is not None else None
        ),
        "global_score_computed_at": (
            global_score.computed_at.isoformat() if global_score is not None else None
        ),
        "forecast": {
            "intraday_job": _job_status_block(compute_forecast_job),
            "official_daily_job": _job_status_block(generate_official_daily_forecast_job),
            "grading_job": _job_status_block(grade_forecasts_job),
            **forecast_health,
        },
    }
