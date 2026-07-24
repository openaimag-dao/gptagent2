import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.config import get_settings
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.market.aggregator import MarketDataAggregator
from app.services.market.repository import MarketRepository

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

MARKET_DATA_JOB_ID = "collect_market_data"


def build_market_aggregator() -> MarketDataAggregator:
    repository = MarketRepository(get_session_factory(), get_redis())
    return MarketDataAggregator(repository)


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
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Scheduler started: collecting market data every %d minute(s)",
        settings.market_data_interval_minutes,
    )
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
