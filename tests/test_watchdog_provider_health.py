from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.onchain.providers import DefiLlamaError
from app.services.watchdog.provider_health import (
    get_provider_status,
    record_provider_failure,
    record_provider_success,
)


def _defillama(tvl=41_000_000_000.0):
    client = AsyncMock()
    client.get_tvl.return_value = tvl
    return client


def _session_factory(scalar_side_effect: list) -> MagicMock:
    session = AsyncMock()
    session.scalar = AsyncMock(side_effect=scalar_side_effect)
    session.execute = AsyncMock()
    session.__aenter__.return_value = session
    return MagicMock(return_value=session)


def _settings(**overrides):
    from types import SimpleNamespace

    base = {
        "fred_api_key": "key",
        "telegram_bot_token": "token",
        "telegram_broadcast_chat_ids": "1,2",
        "gemini_api_key": "key",
        "anthropic_api_key": None,
        "openai_api_key": None,
        "xai_api_key": None,
        "helius_api_key": None,
        "market_data_interval_minutes": 5,
        "realtime_enabled": True,
        "realtime_watchlist": "BTC,ETH",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


async def test_get_provider_status_returns_all_eight_providers():
    now = datetime.now(UTC)
    session_factory = _session_factory([now, now, now, now])
    redis = AsyncMock()
    redis.get.return_value = None

    with patch("app.services.watchdog.provider_health.get_settings", return_value=_settings()):
        providers = await get_provider_status(session_factory, redis, defillama=_defillama())

    names = {p["name"] for p in providers}
    assert names == {
        "CoinGecko",
        "FRED",
        "Coinbase",
        "DefiLlama",
        "Helius",
        "Telegram",
        "Database",
        "Brain",
    }


async def test_coinbase_not_configured_when_realtime_disabled():
    session_factory = _session_factory([None, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = None

    with patch(
        "app.services.watchdog.provider_health.get_settings",
        return_value=_settings(realtime_enabled=False),
    ):
        providers = await get_provider_status(session_factory, redis, defillama=_defillama())

    coinbase = next(p for p in providers if p["name"] == "Coinbase")
    assert coinbase["configured"] is False
    assert "disabled" in coinbase["reason"]


async def test_coinbase_unhealthy_when_collector_has_never_reported_status():
    session_factory = _session_factory([None, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = None

    with patch("app.services.watchdog.provider_health.get_settings", return_value=_settings()):
        providers = await get_provider_status(session_factory, redis, defillama=_defillama())

    coinbase = next(p for p in providers if p["name"] == "Coinbase")
    assert coinbase["configured"] is True
    assert coinbase["healthy"] is False
    assert "offline" in coinbase["reason"]


async def test_coinbase_healthy_when_collector_reports_connected():
    import json

    session_factory = _session_factory([None, None, None, None])
    redis = AsyncMock()

    async def _get(key):
        if key == "realtime:status":
            return json.dumps({"status": "connected", "updated_at": "2026-01-01T00:00:00+00:00"})
        if key == "realtime:latest:BTC":
            return json.dumps(
                {
                    "symbol": "BTC",
                    "price": 100000.0,
                    "source": "coinbase",
                    "event_timestamp": "2026-01-01T00:00:00+00:00",
                    "received_at": "2026-01-01T00:00:00+00:00",
                }
            )
        return None

    redis.get.side_effect = _get

    with patch("app.services.watchdog.provider_health.get_settings", return_value=_settings()):
        providers = await get_provider_status(session_factory, redis, defillama=_defillama())

    coinbase = next(p for p in providers if p["name"] == "Coinbase")
    assert coinbase["configured"] is True
    assert coinbase["healthy"] is True
    assert coinbase["last_successful_update"] is not None
    assert "reason" not in coinbase


async def test_defillama_healthy_when_tvl_fetch_succeeds():
    session_factory = _session_factory([None, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = None

    with patch("app.services.watchdog.provider_health.get_settings", return_value=_settings()):
        providers = await get_provider_status(
            session_factory, redis, defillama=_defillama(tvl=41_000_000_000.0)
        )

    defillama = next(p for p in providers if p["name"] == "DefiLlama")
    assert defillama["configured"] is True
    assert defillama["healthy"] is True
    assert defillama["latency_ms"] is not None


async def test_defillama_unhealthy_when_request_fails():
    session_factory = _session_factory([None, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = None
    defillama_client = AsyncMock()
    defillama_client.get_tvl.side_effect = DefiLlamaError("rate limited")

    with patch("app.services.watchdog.provider_health.get_settings", return_value=_settings()):
        providers = await get_provider_status(session_factory, redis, defillama=defillama_client)

    defillama = next(p for p in providers if p["name"] == "DefiLlama")
    assert defillama["configured"] is True
    assert defillama["healthy"] is False
    assert "failed" in defillama["reason"]


async def test_helius_reports_not_configured_even_with_api_key_set():
    # A settings key existing is not the same as a wallet-level client being
    # wired in -- see app.services.onchain.engine's own docstring.
    session_factory = _session_factory([None, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = None

    with patch(
        "app.services.watchdog.provider_health.get_settings",
        return_value=_settings(helius_api_key="set"),
    ):
        providers = await get_provider_status(session_factory, redis, defillama=_defillama())

    helius = next(p for p in providers if p["name"] == "Helius")
    assert helius["configured"] is True
    assert helius["healthy"] is False
    assert "no wallet-level on-chain client is wired in" in helius["reason"]


async def test_fred_not_configured_when_no_api_key():
    session_factory = _session_factory([None, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = None

    with patch(
        "app.services.watchdog.provider_health.get_settings",
        return_value=_settings(fred_api_key=None),
    ):
        providers = await get_provider_status(session_factory, redis, defillama=_defillama())

    fred = next(p for p in providers if p["name"] == "FRED")
    assert fred["configured"] is False
    assert fred["healthy"] is False


def _redis_get_stub(reconnect_count: str):
    # Blanket-returning a reconnect-count string for every redis.get() call
    # would also feed it to _coinbase_realtime_status's realtime:status/
    # realtime:latest:* reads, which expect JSON -- scope the stub value to
    # the actual reconnect-counter key and return None (honest "no data")
    # for everything else, same as the rest of this file's default mocks.
    async def _get(key):
        return reconnect_count if key.startswith("watchdog:provider_failures:") else None

    return _get


async def test_coingecko_healthy_when_recently_updated():
    now = datetime.now(UTC)
    recent = now - timedelta(minutes=2)
    session_factory = _session_factory([recent, None, None, None])
    redis = AsyncMock()
    redis.get.side_effect = _redis_get_stub("0")

    with patch("app.services.watchdog.provider_health.get_settings", return_value=_settings()):
        providers = await get_provider_status(session_factory, redis, defillama=_defillama())

    coingecko = next(p for p in providers if p["name"] == "CoinGecko")
    assert coingecko["configured"] is True
    assert coingecko["healthy"] is True
    assert coingecko["reconnect_count"] == 0


async def test_coingecko_unhealthy_when_stale():
    now = datetime.now(UTC)
    stale = now - timedelta(hours=5)
    session_factory = _session_factory([stale, None, None, None])
    redis = AsyncMock()
    redis.get.side_effect = _redis_get_stub("3")

    with patch("app.services.watchdog.provider_health.get_settings", return_value=_settings()):
        providers = await get_provider_status(session_factory, redis, defillama=_defillama())

    coingecko = next(p for p in providers if p["name"] == "CoinGecko")
    assert coingecko["healthy"] is False
    assert coingecko["reconnect_count"] == 3


async def test_telegram_not_configured_without_token():
    session_factory = _session_factory([None, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = None

    with patch(
        "app.services.watchdog.provider_health.get_settings",
        return_value=_settings(telegram_bot_token=None),
    ):
        providers = await get_provider_status(session_factory, redis, defillama=_defillama())

    telegram = next(p for p in providers if p["name"] == "Telegram")
    assert telegram["configured"] is False


async def test_brain_configured_when_any_llm_key_present():
    session_factory = _session_factory([None, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = None

    with patch(
        "app.services.watchdog.provider_health.get_settings",
        return_value=_settings(gemini_api_key=None, anthropic_api_key="key"),
    ):
        providers = await get_provider_status(session_factory, redis, defillama=_defillama())

    brain = next(p for p in providers if p["name"] == "Brain")
    assert brain["configured"] is True


async def test_database_health_reports_latency():
    session_factory = _session_factory([None, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = None

    with patch("app.services.watchdog.provider_health.get_settings", return_value=_settings()):
        providers = await get_provider_status(session_factory, redis, defillama=_defillama())

    database = next(p for p in providers if p["name"] == "Database")
    assert database["configured"] is True
    assert database["healthy"] is True
    assert database["latency_ms"] is not None


async def test_record_provider_success_and_failure_only_track_live_providers():
    redis = AsyncMock()

    await record_provider_success(redis, "coingecko")
    redis.set.assert_awaited_once_with("watchdog:provider_failures:coingecko", 0)

    await record_provider_failure(redis, "fred")
    redis.incr.assert_awaited_once_with("watchdog:provider_failures:fred")

    redis.reset_mock()
    await record_provider_success(redis, "twelvedata")
    redis.set.assert_not_awaited()


async def test_record_provider_functions_no_op_without_redis():
    await record_provider_success(None, "coingecko")
    await record_provider_failure(None, "coingecko")
