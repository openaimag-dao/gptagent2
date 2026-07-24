import pytest

from app.services.news.aggregator import NewsAggregator
from app.services.news.base import NewsSource
from app.services.news.schemas import NewsCategory, RawNewsItem


class FakeSource(NewsSource):
    def __init__(
        self, name: str, items: list[RawNewsItem] | None = None, error: Exception | None = None
    ):
        self.name = name
        self.category = NewsCategory.CRYPTO
        self._items = items or []
        self._error = error

    async def fetch(self) -> list[RawNewsItem]:
        if self._error is not None:
            raise self._error
        return self._items


def make_item(title: str) -> RawNewsItem:
    return RawNewsItem(
        title=title,
        url=f"https://example.com/{title}",
        source="fake",
        category=NewsCategory.CRYPTO,
    )


async def test_collect_merges_and_classifies_all_source_items():
    sources = [
        FakeSource("a", items=[make_item("btc-surges")]),
        FakeSource("b", items=[make_item("eth-rallies")]),
    ]
    aggregator = NewsAggregator(repository=None, sources=sources)

    items = await aggregator.collect()

    assert {item.title for item in items} == {"btc-surges", "eth-rallies"}
    assert all(item.sentiment is not None for item in items)


async def test_collect_tolerates_partial_source_failure():
    sources = [
        FakeSource("a", items=[make_item("btc-surges")]),
        FakeSource("b", error=RuntimeError("feed down")),
    ]
    aggregator = NewsAggregator(repository=None, sources=sources)

    items = await aggregator.collect()

    assert [item.title for item in items] == ["btc-surges"]


async def test_collect_raises_when_all_sources_fail():
    sources = [
        FakeSource("a", error=RuntimeError("boom")),
        FakeSource("b", error=RuntimeError("bang")),
    ]
    aggregator = NewsAggregator(repository=None, sources=sources)

    with pytest.raises(RuntimeError, match="All news sources failed"):
        await aggregator.collect()
