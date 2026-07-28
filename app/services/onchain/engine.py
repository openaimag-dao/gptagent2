"""OnChain Intelligence -- v4.0 Phase 3 honest scaffold.

No on-chain data provider (Glassnode, CryptoQuant, Nansen, Helius, etc.) is
wired into this project. Every metric the v4.0 spec calls for -- exchange
netflow/reserves, whale wallet activity, stablecoin supply, TVL,
active/new addresses, dormancy, SOPR, MVRV, NUPL, coin days destroyed,
large transfers, DEX volume, bridge activity -- is reported as honestly
unavailable rather than fabricated, mirroring the established pattern of
WhaleIntelligenceEngine (derivatives-only, no wallet tracker) and
ETFIntelligenceEngine (news-sentiment proxy, not real flow data): this
engine is a documented capability gap, not dead code. `glassnode_api_key`
/ `helius_api_key` exist in Settings so a real client can slot in later
without touching the API/Telegram/dashboard surfaces built on top of it.
"""

from app.config import get_settings
from app.config.settings import Settings

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

_SOLANA_NOTE = (
    "Solana-specific coverage (whale wallet activity, Jupiter/Raydium DEX "
    "volume, Wormhole bridge activity) needs a Solana-native indexer such "
    "as Helius or Solscan Pro -- HELIUS_API_KEY is not configured."
)


class OnChainIntelligenceEngine:
    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def get_snapshot(self, symbol: str) -> dict:
        symbol = symbol.upper()
        snapshot = {
            "symbol": symbol,
            "available": False,
            "reason": self._reason(symbol),
            "metrics": dict.fromkeys(METRICS),
        }
        if symbol == "SOL":
            snapshot["solana_note"] = _SOLANA_NOTE
        return snapshot

    def _reason(self, symbol: str) -> str:
        provider = self._configured_provider(symbol)
        if provider is not None:
            return (
                f"{provider} API key is configured but no on-chain client is wired "
                "in yet -- fetching real on-chain metrics is not implemented in "
                "this build."
            )
        return (
            "No on-chain data provider configured. General on-chain metrics "
            "(exchange netflow/reserves, SOPR, MVRV, NUPL, dormancy, coin days "
            "destroyed, active/new addresses, TVL, stablecoin supply, large "
            "transfers) require GLASSNODE_API_KEY; Solana-specific metrics "
            "require HELIUS_API_KEY. Neither is set."
        )

    def _configured_provider(self, symbol: str) -> str | None:
        if symbol == "SOL" and self._settings.helius_api_key:
            return "Helius"
        if self._settings.glassnode_api_key:
            return "Glassnode"
        return None
