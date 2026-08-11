"""OnChain Intelligence -- partially wired to a real data source.

DefiLlama (free, no API key -- see app.services.onchain.providers) now
supplies real TVL, stablecoin supply and DEX volume for BTC/ETH/SOL. The
rest of the v4.0 spec's metrics -- exchange netflow/reserves, whale wallet
activity, active/new addresses, dormancy, SOPR, MVRV, NUPL, coin days
destroyed, large transfers, bridge activity -- need a wallet-level
indexer (Glassnode/CryptoQuant via GLASSNODE_API_KEY, or a Solana-native
indexer like Helius via HELIUS_API_KEY) that isn't wired in, and stay
honestly `None` rather than fabricated, mirroring the established pattern
of WhaleIntelligenceEngine (derivatives-only, no wallet tracker) and
ETFIntelligenceEngine (news-sentiment proxy, not real flow data).

`available` is True as soon as any real metric comes back this cycle
(same convention as WhaleIntelligenceEngine) -- every consumer built on
top of this engine (ForecastEngine's Confidence Breakdown, Executive
Summary's market_health.onchain_activity, ExplainabilityEngine's On-chain
row, WatchdogEngine.get_onchain_overview, the /api/onchain route, the
dashboard's On-Chain Intelligence page, /onchain in Telegram) already
reads `available`/`reason`/`metrics` generically, so all of them started
reflecting real DefiLlama data the moment this engine did, with no
changes needed in any of them.
"""

import logging

from app.config import get_settings
from app.config.settings import Settings
from app.database.redis import get_redis
from app.services.market.providers.cache import RedisCooldownCache
from app.services.onchain.providers import CHAIN_NAMES, DefiLlamaClient, DefiLlamaError

logger = logging.getLogger(__name__)

METRICS: tuple[str, ...] = (
    "exchange_netflow",
    "exchange_reserves",
    "whale_wallet_activity",
    "stablecoin_supply",
    "tvl",
    "active_addresses",
    "new_addresses",
    "dormancy",
    "sopr",
    "mvrv",
    "nupl",
    "coin_days_destroyed",
    "large_transfers",
    "dex_volume",
    "bridge_activity",
)

_CACHE_TTL_SECONDS = 300

_SOLANA_NOTE = (
    "Solana-specific wallet-level coverage (whale wallet activity, "
    "active/new addresses) needs a Solana-native indexer such as Helius "
    "or Solscan Pro -- HELIUS_API_KEY is not configured. TVL, stablecoin "
    "supply and DEX volume are already covered above via DefiLlama."
)

_WALLET_LEVEL_METRICS = (
    "exchange netflow/reserves, whale wallet activity, active/new addresses, "
    "dormancy, SOPR, MVRV, NUPL, coin days destroyed, large transfers and "
    "bridge activity"
)


class OnChainIntelligenceEngine:
    def __init__(
        self,
        settings: Settings | None = None,
        defillama: DefiLlamaClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._defillama = defillama or DefiLlamaClient()
        self._cache = RedisCooldownCache(get_redis(), "onchain_defillama")

    async def get_snapshot(self, symbol: str) -> dict:
        symbol = symbol.upper()
        metrics = dict.fromkeys(METRICS)

        if symbol in CHAIN_NAMES:
            metrics.update(await self._get_defillama_metrics(symbol))

        available = any(v is not None for v in metrics.values())
        snapshot = {
            "symbol": symbol,
            "available": available,
            "reason": self._reason(symbol, available),
            "metrics": metrics,
        }
        if symbol == "SOL":
            snapshot["solana_note"] = _SOLANA_NOTE
        return snapshot

    async def _get_defillama_metrics(self, symbol: str) -> dict[str, float | None]:
        cached = await self._cache.get(symbol)
        if cached is not None:
            return cached

        tvl = await self._safe_call(self._defillama.get_tvl, symbol)
        stablecoin_supply = await self._safe_call(self._defillama.get_stablecoin_supply, symbol)
        dex_volume = await self._safe_call(self._defillama.get_dex_volume_24h, symbol)
        result = {"tvl": tvl, "stablecoin_supply": stablecoin_supply, "dex_volume": dex_volume}

        if any(v is not None for v in result.values()):
            await self._cache.set(symbol, result, _CACHE_TTL_SECONDS)
        return result

    @staticmethod
    async def _safe_call(fn, symbol: str) -> float | None:
        try:
            return await fn(symbol)
        except DefiLlamaError as exc:
            logger.warning("DefiLlama call failed for %s: %s", symbol, exc)
            return None

    def _reason(self, symbol: str, available: bool) -> str:
        if symbol not in CHAIN_NAMES:
            return (
                "On-chain metrics are only computed for BTC/ETH/SOL (the chains "
                "DefiLlama tracks) -- there is no on-chain concept for this symbol."
            )
        wallet_provider = self._configured_wallet_provider(symbol)
        wallet_note = (
            f"{wallet_provider} API key is configured but no wallet-level client is "
            f"wired in yet -- {_WALLET_LEVEL_METRICS} are still unavailable."
            if wallet_provider is not None
            else f"{_WALLET_LEVEL_METRICS.capitalize()} require GLASSNODE_API_KEY"
            + (" or HELIUS_API_KEY (Solana)" if symbol == "SOL" else "")
            + ", which is not set."
        )
        if available:
            return (
                "TVL, stablecoin supply and DEX volume via DefiLlama (free, no API key). "
                f"{wallet_note}"
            )
        return (
            "DefiLlama request failed this cycle (network or rate limit) -- retrying "
            f"next call. {wallet_note}"
        )

    def _configured_wallet_provider(self, symbol: str) -> str | None:
        if symbol == "SOL" and self._settings.helius_api_key:
            return "Helius"
        if self._settings.glassnode_api_key:
            return "Glassnode"
        return None
