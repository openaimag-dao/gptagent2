import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.analysis.correlation import CorrelationEngine
from app.services.analysis.regime import RegimeDetector
from app.services.market.aggregator import MarketDataAggregator
from app.services.market.repository import MarketRepository
from app.services.news.aggregator import NewsAggregator
from app.services.news.repository import NewsRepository

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

MARKET_DATA_JOB_ID = "collect_market_data"
NEWS_JOB_ID = "collect_news"
CORRELATION_JOB_ID = "compute_correlations"
REGIME_JOB_ID = "detect_regime"


def build_market_aggregator() -> MarketDataAggregator:
    repository = MarketRepository(get_session_factory(), get_redis())
    return MarketDataAggregator(repository)


def build_news_aggregator() -> NewsAggregator:
    repository = NewsRepository(get_session_factory())
    return NewsAggregator(repository)


def build_correlation_engine() -> CorrelationEngine:
    return CorrelationEngine(get_session_factory())


def build_regime_detector() -> RegimeDetector:
    market_repository = MarketRepository(get_session_factory(), get_redis())
    return RegimeDetector(get_session_factory(), market_repository)


async def collect_market_data_job() -> None:
    aggregator = build_market_aggregator()
    try:
        snapshot = await aggregator.collect_and_store()
        logger.info(
            "Market data collected: %d quotes, %d provider errors",
            len(snapshot.quotes),
            len(snapshot.errors),
        )
    except Exception:
        logger.exception("Market data collection job failed")


async def collect_news_job() -> None:
    aggregator = build_news_aggregator()
    try:
        inserted = await aggregator.collect_and_store()
        logger.info("News collected: %d new items stored", inserted)
    except Exception:
        logger.exception("News collection job failed")


async def compute_correlations_job() -> None:
    engine = build_correlation_engine()
    try:
        rows = await engine.compute_and_store()
        logger.info("Correlations computed: %d pair/window combinations", len(rows))
    except Exception:
        logger.exception("Correlation computation job failed")


async def detect_regime_job() -> None:
    detector = build_regime_detector()
    try:
        snapshot = await detector.compute_and_store()
        logger.info("Market regime detected: %s", snapshot.regime.value)
    except Exception:
        logger.exception("Regime detection job failed")


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        collect_market_data_job,
        trigger=IntervalTrigger(minutes=settings.market_data_interval_minutes),
        id=MARKET_DATA_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        collect_news_job,
        trigger=IntervalTrigger(minutes=settings.news_collection_interval_minutes),
        id=NEWS_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        compute_correlations_job,
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes),
        id=CORRELATION_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        detect_regime_job,
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes),
        id=REGIME_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Scheduler started: market data every %d min, news every %d min, analysis every %d min",
        settings.market_data_interval_minutes,
        settings.news_collection_interval_minutes,
        settings.analysis_interval_minutes,
    )
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
