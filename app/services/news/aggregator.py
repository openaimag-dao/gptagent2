import asyncio
import logging

from app.services.news.base import NewsSource
from app.services.news.classifier import classify
from app.services.news.repository import NewsRepository
from app.services.news.schemas import ClassifiedNewsItem
from app.services.news.sources import default_news_sources

logger = logging.getLogger(__name__)


class NewsAggregator:
    """Fetches every news source concurrently, classifies sentiment, and stores new items.

    Mirrors MarketDataAggregator's fault tolerance: one source failing (feed
    down, network blip) is logged and skipped, never aborting the rest. The
    run only raises if every single source fails.
    """

    def __init__(
        self,
        repository: NewsRepository | None,
        sources: list[NewsSource] | None = None,
    ) -> None:
        self._repository = repository
        self._sources = sources if sources is not None else default_news_sources()

    async def collect(self) -> list[ClassifiedNewsItem]:
        results = await asyncio.gather(
            *(source.fetch() for source in self._sources),
            return_exceptions=True,
        )

        classified: list[ClassifiedNewsItem] = []
        failures = 0
        for source, result in zip(self._sources, results):
            if isinstance(result, Exception):
                logger.warning("News source %s failed: %s", source.name, result)
                failures += 1
                continue
            classified.extend(classify(item) for item in result)

        if self._sources and failures == len(self._sources):
            raise RuntimeError("All news sources failed; no data collected")

        return classified

    async def collect_and_store(self) -> int:
        items = await self.collect()
        if self._repository is None:
            return 0
        return await self._repository.save_new_items(items)
