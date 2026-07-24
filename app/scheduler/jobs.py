import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.market.aggregator import MarketDataAggregator
from app.services.market.repository import MarketRepository
from app.services.news.aggregator import NewsAggregator
from app.services.news.repository import NewsRepository

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

MARKET_DATA_JOB_ID = "collect_market_data"
NEWS_JOB_ID = "collect_news"


def build_market_aggregator() -> MarketDataAggregator:
    repository = MarketRepository(get_session_factory(), get_redis())
    return MarketDataAggregator(repository)


def build_news_aggregator() -> NewsAggregator:
    repository = NewsRepository(get_session_factory())
    return NewsAggregator(repository)


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
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Scheduler started: market data every %d minute(s), news every %d minute(s)",
        settings.market_data_interval_minutes,
        settings.news_collection_interval_minutes,
    )
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
