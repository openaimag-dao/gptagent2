from abc import ABC, abstractmethod

from app.services.news.schemas import NewsCategory, RawNewsItem


class NewsSource(ABC):
    """A single feed/source (Fed, SEC, a crypto outlet, ...) yielding raw news items."""

    name: str
    category: NewsCategory

    @abstractmethod
    async def fetch(self) -> list[RawNewsItem]:
        raise NotImplementedError
