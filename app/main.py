import logging
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.backtest import router as backtest_router
from app.api.brain import router as brain_router
from app.api.btc import router as btc_router
from app.api.correlations import router as correlations_router
from app.api.etf import router as etf_router
from app.api.events import router as events_router
from app.api.global_score import router as global_score_router
from app.api.history import router as history_router
from app.api.knowledge import router as knowledge_router
from app.api.market import router as market_router
from app.api.news import router as news_router
from app.api.patterns import router as patterns_router
from app.api.probability import router as probability_router
from app.api.regime import router as regime_router
from app.api.reports import router as reports_router
from app.api.signals import router as signals_router
from app.api.similar import router as similar_router
from app.api.whales import router as whales_router
from app.config import get_settings
from app.scheduler.jobs import shutdown_scheduler, start_scheduler
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


def _redact_url(url: str) -> str:
    """Strips credentials from a connection URL so it's safe to log."""
    return re.sub(r"://[^@/]+@", "://***:***@", url)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Starting AI Market Intelligence Bot (env=%s)", settings.app_env)
    logger.info("Resolved DATABASE_URL: %s", _redact_url(settings.database_url))
    logger.info("Resolved REDIS_URL: %s", _redact_url(settings.redis_url))
    start_scheduler()
    yield
    shutdown_scheduler()


app = FastAPI(
    title="AI Market Intelligence Bot",
    description="Continuous AI-driven analysis of Bitcoin, crypto, US equities and macro markets.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(market_router)
app.include_router(btc_router)
app.include_router(news_router)
app.include_router(correlations_router)
app.include_router(regime_router)
app.include_router(signals_router)
app.include_router(reports_router)
app.include_router(history_router)
app.include_router(events_router)
app.include_router(probability_router)
app.include_router(patterns_router)
app.include_router(knowledge_router)
app.include_router(brain_router)
app.include_router(similar_router)
app.include_router(backtest_router)
app.include_router(etf_router)
app.include_router(whales_router)
app.include_router(global_score_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
