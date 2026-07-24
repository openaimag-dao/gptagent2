import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.correlations import router as correlations_router
from app.api.market import router as market_router
from app.api.news import router as news_router
from app.api.regime import router as regime_router
from app.config import get_settings
from app.scheduler.jobs import shutdown_scheduler, start_scheduler
from app.utils.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    logger.info("Starting AI Market Intelligence Bot (env=%s)", settings.app_env)
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
app.include_router(news_router)
app.include_router(correlations_router)
app.include_router(regime_router)


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
