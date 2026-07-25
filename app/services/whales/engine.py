"""Whale Intelligence.

Exchange inflow/outflow, large-wallet tracking, funding rate, open interest,
liquidations, long/short ratio and stablecoin supply all require a paid,
specialized on-chain/derivatives data source (e.g. Glassnode, CryptoQuant,
Coinglass) -- none is configured anywhere in this project, and there is no
free equivalent with acceptable reliability. Consistent with this project's
rule of never fabricating data (the same rule that keeps
`FredMacroProvider` from inventing a Fed Funds Rate when `FRED_API_KEY` is
unset), this engine reports honestly that it is unavailable rather than
inventing accumulation/distribution numbers. Setting `WHALE_API_KEY` is the
integration point for wiring in a real provider later -- the response shape
below is what that provider would need to fill in.
"""

import logging

from app.config import get_settings

logger = logging.getLogger(__name__)

_RESPONSE_FIELDS = (
    "exchange_netflow",
    "large_wallet_change",
    "funding_rate",
    "open_interest",
    "liquidations_24h",
    "long_short_ratio",
    "stablecoin_supply_change",
    "classification",  # one of: accumulation, distribution, retail_panic, institutional_buying
)


class WhaleIntelligenceEngine:
    def __init__(self) -> None:
        self._settings = get_settings()

    async def get_snapshot(self, symbol: str = "BTC") -> dict:
        if not self._settings.whale_api_key:
            return {
                "available": False,
                "symbol": symbol.upper(),
                "reason": (
                    "WHALE_API_KEY is not configured; on-chain/derivatives data "
                    "(exchange flows, funding rate, open interest, liquidations, "
                    "long/short ratio, stablecoin supply) requires a paid provider "
                    "such as Glassnode, CryptoQuant or Coinglass."
                ),
                "would_return": list(_RESPONSE_FIELDS),
            }

        # No provider is wired up yet even with a key present -- report that
        # honestly too, rather than silently returning nothing useful.
        return {
            "available": False,
            "symbol": symbol.upper(),
            "reason": (
                "WHALE_API_KEY is set, but no whale-data provider is implemented "
                "yet. Add one under app/services/whales/providers/ implementing "
                "this engine's get_snapshot() response shape."
            ),
            "would_return": list(_RESPONSE_FIELDS),
        }
