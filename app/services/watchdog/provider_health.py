"""Honest, non-fabricated provider health for the Watchdog "Provider
Status" panel. Every field is either a real, cheap live probe (Database,
DefiLlama), derived from a timestamp/counter another part of this platform
already stores (AssetPrice.recorded_at per source, AlertLog.triggered_at,
Report.generated_at, a Redis failure counter incremented by
collect_market_data_job), or read from RealtimePriceCollector's live
Redis-published connection state (Binance -- see
app.services.realtime.collector). Helius/Glassnode have a settings field
but no wired wallet-level client (see app.services.onchain.engine's own
docstring) -- reported not-configured/not-implemented, never faked,
matching this project's "never fabricate values" precedent everywhere
else.
"""

import asyncio
import time
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import AlertLog, AssetPrice, Report
from app.services.onchain.providers import DefiLlamaClient, DefiLlamaError
from app.services.realtime.config import parse_watchlist
from app.services.realtime.store import get_latest_ticks, get_status

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


async def _binance_realtime_status(redis: Redis | None) -> dict:
    """Live Dashboard Upgrade -- previously this row was permanently
    hardcoded not-configured because no Binance client existed anywhere in
    this codebase (see this module's own docstring). Now reads
    RealtimePriceCollector's real Redis-published state instead of a
    static string -- still honestly reports "not connected" if the
    collector hasn't produced a status yet, never fabricates "healthy"."""
    settings = get_settings()
    if not settings.realtime_enabled:
        return {
            "name": "Binance",
            "configured": False,
            "healthy": False,
            "latency_ms": None,
            "reconnect_count": None,
            "last_successful_update": None,
            "reason": "Realtime price stream is disabled (realtime_enabled=false).",
        }
    if redis is None:
        return {
            "name": "Binance",
            "configured": True,
            "healthy": False,
            "latency_ms": None,
            "reconnect_count": None,
            "last_successful_update": None,
            "reason": "Redis unavailable -- cannot read realtime collector status.",
        }
    status = await get_status(redis)
    latest = await get_latest_ticks(redis, parse_watchlist(settings.realtime_watchlist))
    most_recent = max((tick.received_at for tick in latest.values()), default=None)
    healthy = status["status"] == "connected"
    result = {
        "name": "Binance",
        "configured": True,
        "healthy": healthy,
        "latency_ms": None,
        "reconnect_count": None,
        "last_successful_update": most_recent.isoformat() if most_recent is not None else None,
    }
    if not healthy:
        result["reason"] = f"Realtime WebSocket status: {status['status']}."
    return result


async def _defillama_health(defillama: DefiLlamaClient) -> dict:
    """Unlike CoinGecko/FRED (inferred from AssetPrice write recency,
    never live-probed -- see module docstring), DefiLlama has no
    scheduler job feeding a periodic "last successful write" timestamp to
    check recency against (OnChainIntelligenceEngine only fetches
    on-demand, per request). A cheap, free, unauthenticated single call
    is the only honest way to know current health, and DefiLlama's public
    API documents no strict per-minute limit the way CoinGecko's free
    tier does, so this stays a live probe rather than an inferred read."""
    start = time.monotonic()
    try:
        tvl = await defillama.get_tvl("BTC")
    except DefiLlamaError:
        return {
            "name": "DefiLlama",
            "configured": True,
            "healthy": False,
            "latency_ms": None,
            "reconnect_count": None,
            "last_successful_update": None,
            "reason": "DefiLlama request failed this cycle (network or rate limit).",
        }
    latency_ms = round((time.monotonic() - start) * 1000, 1)
    healthy = tvl is not None
    return {
        "name": "DefiLlama",
        "configured": True,
        "healthy": healthy,
        "latency_ms": latency_ms,
        "reconnect_count": None,
        "last_successful_update": datetime.now(UTC).isoformat() if healthy else None,
    }


async def get_provider_status(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis | None,
    defillama: DefiLlamaClient | None = None,
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

    database, defillama_health, binance = await asyncio.gather(
        _database_health(session_factory),
        _defillama_health(defillama or DefiLlamaClient()),
        _binance_realtime_status(redis),
    )

    helius = {
        "name": "Helius",
        "configured": bool(settings.helius_api_key),
        "healthy": False,
        "latency_ms": None,
        "reconnect_count": None,
        "last_successful_update": None,
        "reason": (
            "HELIUS_API_KEY can be set, but no wallet-level on-chain client is wired "
            "in yet -- see app.services.onchain.engine. TVL/stablecoin supply/DEX "
            "volume are already covered by DefiLlama above."
        ),
    }

    return [coingecko, fred, binance, defillama_health, helius, telegram, database, brain]
