from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.watchdog.provider_health import (
    get_provider_status,
    record_provider_failure,
    record_provider_success,
)


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
    }
    base.update(overrides)
    return SimpleNamespace(**base)


async def test_get_provider_status_returns_all_eight_providers():
    now = datetime.now(UTC)
    session_factory = _session_factory([now, now, now, now])
    redis = AsyncMock()
    redis.get.return_value = None

    with patch("app.services.watchdog.provider_health.get_settings", return_value=_settings()):
        providers = await get_provider_status(session_factory, redis)

    names = {p["name"] for p in providers}
    assert names == {
        "CoinGecko",
        "FRED",
        "Binance",
        "DefiLlama",
        "Helius",
        "Telegram",
        "Database",
        "Brain",
    }


async def test_binance_and_defillama_always_report_not_implemented():
    session_factory = _session_factory([None, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = None

    with patch("app.services.watchdog.provider_health.get_settings", return_value=_settings()):
        providers = await get_provider_status(session_factory, redis)

    by_name = {p["name"]: p for p in providers}
    assert by_name["Binance"]["configured"] is False
    assert "No Binance client" in by_name["Binance"]["reason"]
    assert by_name["DefiLlama"]["configured"] is False
    assert "No DefiLlama client" in by_name["DefiLlama"]["reason"]


async def test_helius_reports_not_configured_even_with_api_key_set():
    # A settings key existing is not the same as a client being wired in --
    # see app.services.onchain.engine's own honest-scaffold pattern.
    session_factory = _session_factory([None, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = None

    with patch(
        "app.services.watchdog.provider_health.get_settings",
        return_value=_settings(helius_api_key="set"),
    ):
        providers = await get_provider_status(session_factory, redis)

    helius = next(p for p in providers if p["name"] == "Helius")
    assert helius["configured"] is True
    assert helius["healthy"] is False
    assert "no on-chain client is wired in" in helius["reason"]


async def test_fred_not_configured_when_no_api_key():
    session_factory = _session_factory([None, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = None

    with patch(
        "app.services.watchdog.provider_health.get_settings",
        return_value=_settings(fred_api_key=None),
    ):
        providers = await get_provider_status(session_factory, redis)

    fred = next(p for p in providers if p["name"] == "FRED")
    assert fred["configured"] is False
    assert fred["healthy"] is False


async def test_coingecko_healthy_when_recently_updated():
    now = datetime.now(UTC)
    recent = now - timedelta(minutes=2)
    session_factory = _session_factory([recent, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = "0"

    with patch("app.services.watchdog.provider_health.get_settings", return_value=_settings()):
        providers = await get_provider_status(session_factory, redis)

    coingecko = next(p for p in providers if p["name"] == "CoinGecko")
    assert coingecko["configured"] is True
    assert coingecko["healthy"] is True
    assert coingecko["reconnect_count"] == 0


async def test_coingecko_unhealthy_when_stale():
    now = datetime.now(UTC)
    stale = now - timedelta(hours=5)
    session_factory = _session_factory([stale, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = "3"

    with patch("app.services.watchdog.provider_health.get_settings", return_value=_settings()):
        providers = await get_provider_status(session_factory, redis)

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
        providers = await get_provider_status(session_factory, redis)

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
        providers = await get_provider_status(session_factory, redis)

    brain = next(p for p in providers if p["name"] == "Brain")
    assert brain["configured"] is True


async def test_database_health_reports_latency():
    session_factory = _session_factory([None, None, None, None])
    redis = AsyncMock()
    redis.get.return_value = None

    with patch("app.services.watchdog.provider_health.get_settings", return_value=_settings()):
        providers = await get_provider_status(session_factory, redis)

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
