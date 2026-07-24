import pytest

from app.services.market.aggregator import MarketDataAggregator
from app.services.market.base import MarketDataProvider
from app.services.market.schemas import AssetClass, AssetQuote


class FakeProvider(MarketDataProvider):
    def __init__(
        self,
        name: str,
        quotes: list[AssetQuote] | None = None,
        error: Exception | None = None,
    ):
        self.name = name
        self._quotes = quotes or []
        self._error = error

    async def fetch(self) -> list[AssetQuote]:
        if self._error is not None:
            raise self._error
        return self._quotes


def make_quote(symbol: str) -> AssetQuote:
    return AssetQuote(
        symbol=symbol,
        name=symbol,
        asset_class=AssetClass.CRYPTO,
        price=100.0,
        source="fake",
    )


async def test_collect_merges_all_provider_quotes():
    providers = [
        FakeProvider("a", quotes=[make_quote("BTC")]),
        FakeProvider("b", quotes=[make_quote("ETH")]),
    ]
    aggregator = MarketDataAggregator(repository=None, providers=providers)

    snapshot = await aggregator.collect()

    assert {q.symbol for q in snapshot.quotes} == {"BTC", "ETH"}
    assert snapshot.errors == []


async def test_collect_tolerates_partial_provider_failure():
    providers = [
        FakeProvider("a", quotes=[make_quote("BTC")]),
        FakeProvider("b", error=RuntimeError("boom")),
    ]
    aggregator = MarketDataAggregator(repository=None, providers=providers)

    snapshot = await aggregator.collect()

    assert [q.symbol for q in snapshot.quotes] == ["BTC"]
    assert len(snapshot.errors) == 1
    assert "boom" in snapshot.errors[0]


async def test_collect_raises_when_all_providers_fail():
    providers = [
        FakeProvider("a", error=RuntimeError("boom")),
        FakeProvider("b", error=RuntimeError("bang")),
    ]
    aggregator = MarketDataAggregator(repository=None, providers=providers)

    with pytest.raises(RuntimeError, match="All market data providers failed"):
        await aggregator.collect()
