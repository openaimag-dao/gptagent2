"""DefiLlama client -- free, keyless on-chain aggregates (TVL, stablecoin
supply, DEX volume) per chain. Unlike CoinGlass/Glassnode/Helius, DefiLlama
needs no API key at all, matching the same "genuinely free, always-available"
precedent CoinGeckoDerivativesClient established for whale/derivatives data
(see app/services/whales/providers/coingecko_derivatives.py).

DefiLlama is a DeFi/TVL aggregator, not a wallet-level on-chain indexer: it
cannot supply exchange netflow/reserves, whale wallet activity, active/new
addresses, dormancy, SOPR, MVRV, NUPL, coin days destroyed, large transfers
or bridge activity -- those genuinely need Glassnode/CryptoQuant
(GLASSNODE_API_KEY) or a Solana-native indexer like Helius
(HELIUS_API_KEY). This client never claims those metrics.
"""

import logging

import httpx

from app.config import get_settings
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

_CHAINS_URL = "https://api.llama.fi/v2/chains"
_STABLECOIN_CHAINS_URL = "https://stablecoins.llama.fi/stablecoinchains"
_DEX_OVERVIEW_URL = "https://api.llama.fi/overview/dexs/{chain}"

# DefiLlama's own chain-name spelling, keyed by this project's asset symbols.
CHAIN_NAMES: dict[str, str] = {
    "BTC": "Bitcoin",
    "ETH": "Ethereum",
    "SOL": "Solana",
}


class DefiLlamaError(RuntimeError):
    pass


class DefiLlamaClient:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def configured(self) -> bool:
        # No API key required -- always usable.
        return True

    @default_retry()
    async def _get_json(self, client: httpx.AsyncClient, url: str) -> object:
        response = await client.get(url)
        response.raise_for_status()
        return response.json()

    async def get_tvl(self, symbol: str) -> float | None:
        """Current Total Value Locked for `symbol`'s chain, in USD."""
        chain = CHAIN_NAMES.get(symbol.upper())
        if chain is None:
            return None
        try:
            async with build_http_client(self._settings.http_timeout_seconds) as client:
                payload = await self._get_json(client, _CHAINS_URL)
        except httpx.HTTPError as exc:
            raise DefiLlamaError(f"DefiLlama chains fetch failed: {exc}") from exc
        if not isinstance(payload, list):
            return None
        for entry in payload:
            if isinstance(entry, dict) and entry.get("name") == chain:
                tvl = entry.get("tvl")
                return float(tvl) if tvl is not None else None
        return None

    async def get_stablecoin_supply(self, symbol: str) -> float | None:
        """Total circulating USD-pegged stablecoin supply on `symbol`'s chain."""
        chain = CHAIN_NAMES.get(symbol.upper())
        if chain is None:
            return None
        try:
            async with build_http_client(self._settings.http_timeout_seconds) as client:
                payload = await self._get_json(client, _STABLECOIN_CHAINS_URL)
        except httpx.HTTPError as exc:
            raise DefiLlamaError(f"DefiLlama stablecoin chains fetch failed: {exc}") from exc
        if not isinstance(payload, list):
            return None
        for entry in payload:
            if isinstance(entry, dict) and entry.get("name") == chain:
                circulating = (entry.get("totalCirculatingUSD") or {}).get("peggedUSD")
                return float(circulating) if circulating is not None else None
        return None

    async def get_dex_volume_24h(self, symbol: str) -> float | None:
        """Trailing 24h DEX trading volume on `symbol`'s chain, in USD."""
        chain = CHAIN_NAMES.get(symbol.upper())
        if chain is None:
            return None
        url = _DEX_OVERVIEW_URL.format(chain=chain.lower())
        try:
            async with build_http_client(self._settings.http_timeout_seconds) as client:
                payload = await self._get_json(
                    client,
                    f"{url}?excludeTotalDataChart=true&excludeTotalDataChartBreakdown=true",
                )
        except httpx.HTTPError as exc:
            raise DefiLlamaError(f"DefiLlama dexs overview fetch failed: {exc}") from exc
        if not isinstance(payload, dict):
            return None
        total_24h = payload.get("total24h")
        return float(total_24h) if total_24h is not None else None
