"""CoinGecko `/coins/markets` client for the v5.5 Market Scanner -- fetches
the top-N cryptocurrencies by market cap (paginated, 250/page) plus
individual lookups for the mission's "always include" symbols that may
have fallen out of the top N. Distinct from
`app.services.market.crypto.coingecko.CoinGeckoProvider` (BTC/ETH/SOL
only, feeds the existing AssetPrice pipeline that Regime/GlobalScore/etc.
already consume) -- this client feeds the scanner's own ScannerSnapshot
history instead, and needs a much wider, ranked universe. Both clients
share the same `coingecko_api_key`/`coingecko_base_url` settings and the
same retry/timeout helpers (`app.utils.http`), nothing duplicated there.
"""

import logging
from typing import Any

import httpx

from app.config import get_settings
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

_PAGE_SIZE = 250
_PRICE_CHANGE_FIELDS = "1h,24h"


class CoinGeckoMarketsClient:
    name = "coingecko_scanner"

    def __init__(self) -> None:
        self._settings = get_settings()

    def _headers(self) -> dict[str, str]:
        if self._settings.coingecko_api_key:
            return {"x-cg-demo-api-key": self._settings.coingecko_api_key}
        return {}

    @default_retry()
    async def _get(self, client: httpx.AsyncClient, params: dict[str, Any]) -> Any:
        response = await client.get(
            f"{self._settings.coingecko_base_url}/coins/markets",
            params=params,
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def fetch_top(self, limit: int) -> list[dict]:
        """Top `limit` coins by market cap, ranked -- fetched in full
        `_PAGE_SIZE`-coin pages (CoinGecko's per-request cap)."""
        pages = -(-limit // _PAGE_SIZE)  # ceil division
        coins: list[dict] = []
        async with build_http_client(self._settings.http_timeout_seconds) as client:
            for page in range(1, pages + 1):
                batch = await self._get(
                    client,
                    {
                        "vs_currency": "usd",
                        "order": "market_cap_desc",
                        "per_page": _PAGE_SIZE,
                        "page": page,
                        "price_change_percentage": _PRICE_CHANGE_FIELDS,
                        "sparkline": "false",
                    },
                )
                if not batch:
                    break
                coins.extend(batch)
        return coins[:limit]

    async def fetch_by_ids(self, coingecko_ids: list[str]) -> list[dict]:
        """Looks up specific coins by CoinGecko id regardless of market-cap
        rank -- used to keep the mission's "always include" symbols
        covered even when they've fallen out of the top N."""
        if not coingecko_ids:
            return []
        async with build_http_client(self._settings.http_timeout_seconds) as client:
            return await self._get(
                client,
                {
                    "vs_currency": "usd",
                    "ids": ",".join(coingecko_ids),
                    "price_change_percentage": _PRICE_CHANGE_FIELDS,
                    "sparkline": "false",
                },
            )
