from unittest.mock import AsyncMock

from app.services.market.providers.cache import RedisCooldownCache


async def test_get_returns_none_when_key_missing():
    redis_client = AsyncMock()
    redis_client.get.return_value = None
    cache = RedisCooldownCache(redis_client, "twelvedata")

    result = await cache.get("stocks")

    assert result is None
    redis_client.get.assert_awaited_once_with("provider_cooldown:twelvedata:stocks")


async def test_get_deserializes_json():
    redis_client = AsyncMock()
    redis_client.get.return_value = '[{"symbol": "AAPL", "price": 100.0}]'
    cache = RedisCooldownCache(redis_client, "twelvedata")

    result = await cache.get("stocks")

    assert result == [{"symbol": "AAPL", "price": 100.0}]


async def test_get_returns_none_on_corrupt_json():
    redis_client = AsyncMock()
    redis_client.get.return_value = "not json"
    cache = RedisCooldownCache(redis_client, "twelvedata")

    result = await cache.get("stocks")

    assert result is None


async def test_set_serializes_with_ttl():
    redis_client = AsyncMock()
    cache = RedisCooldownCache(redis_client, "alphavantage")

    await cache.set("news", [{"title": "x"}], ttl_seconds=3600)

    redis_client.set.assert_awaited_once_with(
        "provider_cooldown:alphavantage:news", '[{"title": "x"}]', ex=3600
    )


async def test_namespaces_keep_keys_isolated():
    redis_client = AsyncMock()
    cache_a = RedisCooldownCache(redis_client, "twelvedata")
    cache_b = RedisCooldownCache(redis_client, "alphavantage")

    await cache_a.set("stocks", [], ttl_seconds=60)
    await cache_b.set("stocks", [], ttl_seconds=60)

    keys_used = [call.args[0] for call in redis_client.set.await_args_list]
    assert keys_used == [
        "provider_cooldown:twelvedata:stocks",
        "provider_cooldown:alphavantage:stocks",
    ]
