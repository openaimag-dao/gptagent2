import json
from unittest.mock import AsyncMock

from app.services.scanner.universe import ALWAYS_INCLUDE, ScannerUniverse


def _coin(symbol: str, coingecko_id: str, rank: int) -> dict:
    return {"id": coingecko_id, "symbol": symbol.lower(), "name": symbol, "market_cap_rank": rank}


async def test_get_universe_returns_cached_when_present():
    client = AsyncMock()
    redis = AsyncMock()
    cached = [{"symbol": "BTC", "name": "Bitcoin", "coingecko_id": "bitcoin", "market_cap_rank": 1}]
    redis.get.return_value = json.dumps(cached)

    universe = ScannerUniverse(client, redis)
    result = await universe.get_universe()

    assert result == cached
    client.fetch_top.assert_not_awaited()


async def test_get_universe_fetches_fresh_on_cache_miss():
    client = AsyncMock()
    client.fetch_top.return_value = [_coin("BTC", "bitcoin", 1)]
    client.fetch_by_ids.return_value = []
    redis = AsyncMock()
    redis.get.return_value = None

    universe = ScannerUniverse(client, redis)
    result = await universe.get_universe(top_n=1)

    assert result[0]["symbol"] == "BTC"
    redis.set.assert_awaited_once()


async def test_always_include_symbols_merged_even_when_missing_from_top_n():
    client = AsyncMock()
    client.fetch_top.return_value = [_coin("BTC", "bitcoin", 1)]  # only BTC in "top N"
    # every ALWAYS_INCLUDE symbol except BTC needs a fallback lookup
    client.fetch_by_ids.return_value = [
        _coin(symbol, coingecko_id, 900)
        for symbol, coingecko_id in ALWAYS_INCLUDE.items()
        if symbol != "BTC"
    ]
    redis = AsyncMock()
    redis.get.return_value = None

    universe = ScannerUniverse(client, redis)
    result = await universe.refresh(top_n=1)

    symbols = {entry["symbol"] for entry in result}
    assert symbols == set(ALWAYS_INCLUDE.keys())
    fetch_by_ids_args = client.fetch_by_ids.call_args.args[0]
    assert "bitcoin" not in fetch_by_ids_args  # BTC already present, no redundant lookup


async def test_refresh_bypasses_cache():
    client = AsyncMock()
    client.fetch_top.return_value = [_coin("BTC", "bitcoin", 1)]
    client.fetch_by_ids.return_value = []
    redis = AsyncMock()

    universe = ScannerUniverse(client, redis)
    await universe.refresh(top_n=1)

    redis.get.assert_not_awaited()
    client.fetch_top.assert_awaited_once()


async def test_get_universe_without_redis_always_fetches_fresh():
    client = AsyncMock()
    client.fetch_top.return_value = [_coin("BTC", "bitcoin", 1)]
    client.fetch_by_ids.return_value = []

    universe = ScannerUniverse(client, None)
    result = await universe.get_universe(top_n=1)

    assert result[0]["symbol"] == "BTC"
