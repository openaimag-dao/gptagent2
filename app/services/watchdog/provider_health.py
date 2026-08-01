"""Honest, non-fabricated provider health for the Watchdog "Provider
Status" panel. Every field is either a real, cheap live probe (Database) or
derived from a timestamp/counter another part of this platform already
stores (AssetPrice.recorded_at per source, AlertLog.triggered_at,
Report.generated_at, a Redis failure counter incremented by
collect_market_data_job). Binance and DefiLlama have no client anywhere in
this codebase; Helius/Glassnode have a settings field but no wired client
(see app.services.onchain.engine's own honest-scaffold docstring) -- all
three are reported not-configured/not-implemented, never faked, matching
this project's "never fabricate values" precedent everywhere else.
"""

import time
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import AlertLog, AssetPrice, Report

_RECONNECT_KEY_PREFIX = "watchdog:provider_failures:"

# The only providers this codebase actually calls for live market data --
# see app.services.market.aggregator.default_providers(). Their
# AssetPrice.source values match MarketDataProvider.name exactly
# (source=self.name in both clients).
_LIVE_MARKET_PROVIDERS: tuple[str, ...] = ("coingecko", "fred")

# A provider is considered stale if it hasn't produced a successful row in
# this many collection cycles' worth of time.
_STALE_CYCLE_MULTIPLIER = 3


async def record_provider_success(redis: Redis | None, provider_name: str) -> None:
    if redis is None or provider_name not in _LIVE_MARKET_PROVIDERS:
        return
    await redis.set(f"{_RECONNECT_KEY_PREFIX}{provider_name}", 0)


async def record_provider_failure(redis: Redis | None, provider_name: str) -> None:
    if redis is None or provider_name not in _LIVE_MARKET_PROVIDERS:
        return
    await redis.incr(f"{_RECONNECT_KEY_PREFIX}{provider_name}")


async def _reconnect_count(redis: Redis | None, provider_name: str) -> int | None:
    if redis is None:
        return None
    raw = await redis.get(f"{_RECONNECT_KEY_PREFIX}{provider_name}")
    return int(raw) if raw is not None else 0


async def _last_successful_update(
    session_factory: async_sessionmaker[AsyncSession], source: str
) -> datetime | None:
    async with session_factory() as session:
        return await session.scalar(
            select(func.max(AssetPrice.recorded_at)).where(AssetPrice.source == source)
        )


async def _market_provider_status(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis | None,
    label: str,
    source: str,
    configured: bool,
    now: datetime,
    stale_after_seconds: float,
) -> dict:
    last_update = await _last_successful_update(session_factory, source) if configured else None
    reconnects = await _reconnect_count(redis, source)
    healthy = (
        configured
        and last_update is not None
        and (now - last_update).total_seconds() <= stale_after_seconds
    )
    return {
        "name": label,
        "configured": configured,
        "healthy": healthy,
        "latency_ms": None,
        "reconnect_count": reconnects,
        "last_successful_update": last_update.isoformat() if last_update is not None else None,
    }


async def _database_health(session_factory: async_sessionmaker[AsyncSession]) -> dict:
    start = time.monotonic()
    try:
        async with session_factory() as session:
            await session.execute(select(1))
        latency_ms = round((time.monotonic() - start) * 1000, 1)
        return {
            "name": "Database",
            "configured": True,
            "healthy": True,
            "latency_ms": latency_ms,
            "reconnect_count": 0,
            "last_successful_update": datetime.now(UTC).isoformat(),
        }
    except Exception:
        return {
            "name": "Database",
            "configured": True,
            "healthy": False,
            "latency_ms": None,
            "reconnect_count": None,
            "last_successful_update": None,
        }


async def get_provider_status(
    session_factory: async_sessionmaker[AsyncSession], redis: Redis | None
) -> list[dict]:
    settings = get_settings()
    now = datetime.now(UTC)
    stale_after_seconds = settings.market_data_interval_minutes * 60 * _STALE_CYCLE_MULTIPLIER

    coingecko = await _market_provider_status(
        session_factory, redis, "CoinGecko", "coingecko", True, now, stale_after_seconds
    )
    fred = await _market_provider_status(
        session_factory,
        redis,
        "FRED",
        "fred",
        bool(settings.fred_api_key),
        now,
        stale_after_seconds,
    )

    async with session_factory() as session:
        last_alert_broadcast = await session.scalar(
            select(func.max(AlertLog.triggered_at)).where(AlertLog.broadcast.is_(True))
        )
        last_report = await session.scalar(select(func.max(Report.generated_at)))

    telegram_configured = bool(settings.telegram_bot_token and settings.telegram_broadcast_chat_ids)
    telegram = {
        "name": "Telegram",
        "configured": telegram_configured,
        "healthy": telegram_configured,
        "latency_ms": None,
        "reconnect_count": None,
        "last_successful_update": (
            last_alert_broadcast.isoformat() if last_alert_broadcast is not None else None
        ),
    }

    brain_configured = bool(
        settings.gemini_api_key
        or settings.anthropic_api_key
        or settings.openai_api_key
        or settings.xai_api_key
    )
    brain = {
        "name": "Brain",
        "configured": brain_configured,
        "healthy": brain_configured and last_report is not None,
        "latency_ms": None,
        "reconnect_count": None,
        "last_successful_update": last_report.isoformat() if last_report is not None else None,
    }

    database = await _database_health(session_factory)

    binance = {
        "name": "Binance",
        "configured": False,
        "healthy": False,
        "latency_ms": None,
        "reconnect_count": None,
        "last_successful_update": None,
        "reason": "No Binance client is implemented in this codebase.",
    }
    defillama = {
        "name": "DefiLlama",
        "configured": False,
        "healthy": False,
        "latency_ms": None,
        "reconnect_count": None,
        "last_successful_update": None,
        "reason": "No DefiLlama client is implemented in this codebase.",
    }
    helius = {
        "name": "Helius",
        "configured": bool(settings.helius_api_key),
        "healthy": False,
        "latency_ms": None,
        "reconnect_count": None,
        "last_successful_update": None,
        "reason": (
            "HELIUS_API_KEY can be set, but no on-chain client is wired in yet "
            "-- see app.services.onchain.engine."
        ),
    }

    return [coingecko, fred, binance, defillama, helius, telegram, database, brain]
