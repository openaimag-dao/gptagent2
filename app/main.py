import asyncio
import contextlib
import logging
import re
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.accuracy import router as accuracy_router
from app.api.admin import router as admin_router
from app.api.agents import router as agents_router
from app.api.alert_performance import router as alert_performance_router
from app.api.alerts import router as alerts_router
from app.api.backtest import router as backtest_router
from app.api.brain import router as brain_router
from app.api.breakout import router as breakout_router
from app.api.btc import router as btc_router
from app.api.calendar import router as calendar_router
from app.api.committee import router as committee_router
from app.api.consensus import router as consensus_router
from app.api.conviction import router as conviction_router
from app.api.correlations import router as correlations_router
from app.api.data_quality import router as data_quality_router
from app.api.etf import router as etf_router
from app.api.events import router as events_router
from app.api.executive_summary import router as executive_summary_router
from app.api.explanation import router as explanation_router
from app.api.features import router as features_router
from app.api.forecast import router as forecast_router
from app.api.futures_sim import router as futures_sim_router
from app.api.global_score import router as global_score_router
from app.api.history import router as history_router
from app.api.hypothesis import router as hypothesis_router
from app.api.knowledge import router as knowledge_router
from app.api.learning import router as learning_router
from app.api.liquidity import router as liquidity_router
from app.api.market import router as market_router
from app.api.memory import router as memory_router
from app.api.news import router as news_router
from app.api.no_trade import router as no_trade_router
from app.api.onchain import router as onchain_router
from app.api.opportunities import router as opportunities_router
from app.api.patterns import router as patterns_router
from app.api.portfolio import router as portfolio_router
from app.api.probability import router as probability_router
from app.api.quality import router as quality_router
from app.api.ranking import router as ranking_router
from app.api.realtime import router as realtime_router
from app.api.regime import router as regime_router
from app.api.replay import router as replay_router
from app.api.reports import router as reports_router
from app.api.research import router as research_router
from app.api.risk import router as risk_router
from app.api.scanner import router as scanner_router
from app.api.scenarios import router as scenarios_router
from app.api.sentiment import router as sentiment_router
from app.api.shocks import router as shocks_router
from app.api.signals import router as signals_router
from app.api.similar import router as similar_router
from app.api.status import router as status_router
from app.api.strategy import router as strategy_router
from app.api.technical import router as technical_router
from app.api.terminal import router as terminal_router
from app.api.trade_setup import router as trade_setup_router
from app.api.watchdog import router as watchdog_router
from app.api.whales import router as whales_router
from app.api.whatif import router as whatif_router
from app.config import get_settings
from app.scheduler.jobs import shutdown_scheduler, start_scheduler
from app.services.realtime.collector import build_realtime_collector
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
    realtime_task = (
        asyncio.create_task(build_realtime_collector().run()) if settings.realtime_enabled else None
    )
    yield
    shutdown_scheduler()
    if realtime_task is not None:
        realtime_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await realtime_task


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
app.include_router(data_quality_router)
app.include_router(regime_router)
app.include_router(signals_router)
app.include_router(reports_router)
app.include_router(history_router)
app.include_router(events_router)
app.include_router(calendar_router)
app.include_router(features_router)
app.include_router(forecast_router)
app.include_router(futures_sim_router)
app.include_router(no_trade_router)
app.include_router(research_router)
app.include_router(strategy_router)
app.include_router(hypothesis_router)
app.include_router(ranking_router)
app.include_router(probability_router)
app.include_router(patterns_router)
app.include_router(knowledge_router)
app.include_router(brain_router)
app.include_router(similar_router)
app.include_router(backtest_router)
app.include_router(etf_router)
app.include_router(whales_router)
app.include_router(global_score_router)
app.include_router(sentiment_router)
app.include_router(agents_router)
app.include_router(memory_router)
app.include_router(scenarios_router)
app.include_router(whatif_router)
app.include_router(terminal_router)
app.include_router(conviction_router)
app.include_router(portfolio_router)
app.include_router(liquidity_router)
app.include_router(admin_router)
app.include_router(consensus_router)
app.include_router(committee_router)
app.include_router(learning_router)
app.include_router(quality_router)
app.include_router(explanation_router)
app.include_router(status_router)
app.include_router(risk_router)
app.include_router(replay_router)
app.include_router(breakout_router)
app.include_router(onchain_router)
app.include_router(opportunities_router)
app.include_router(alerts_router)
app.include_router(alert_performance_router)
app.include_router(shocks_router)
app.include_router(technical_router)
app.include_router(watchdog_router)
app.include_router(scanner_router)
app.include_router(executive_summary_router)
app.include_router(accuracy_router)
app.include_router(trade_setup_router)
app.include_router(realtime_router)

_DASHBOARD_DIR = Path(__file__).parent / "static" / "dashboard"
app.mount("/dashboard", StaticFiles(directory=_DASHBOARD_DIR, html=True), name="dashboard")


@app.get("/health", tags=["system"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
