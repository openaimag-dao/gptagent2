import logging
from typing import Any

import httpx

from app.config import get_settings
from app.services.market.base import MarketDataProvider
from app.services.market.schemas import AssetClass, AssetQuote
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

# CoinGecko coin id -> (display symbol, display name)
COINGECKO_IDS: dict[str, tuple[str, str]] = {
    "bitcoin": ("BTC", "Bitcoin"),
    "ethereum": ("ETH", "Ethereum"),
    "solana": ("SOL", "Solana"),
}


class CoinGeckoProvider(MarketDataProvider):
    """Fetches BTC/ETH/SOL market data plus total crypto market cap and BTC dominance."""

    name = "coingecko"

    def __init__(self) -> None:
        self._settings = get_settings()

    def _headers(self) -> dict[str, str]:
        if self._settings.coingecko_api_key:
            return {"x-cg-demo-api-key": self._settings.coingecko_api_key}
        return {}

    @default_retry()
    async def _get(self, client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> Any:
        response = await client.get(
            f"{self._settings.coingecko_base_url}{path}",
            params=params,
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def fetch(self) -> list[AssetQuote]:
        quotes: list[AssetQuote] = []
        async with build_http_client(self._settings.http_timeout_seconds) as client:
            markets = await self._get(
                client,
                "/coins/markets",
                {
                    "vs_currency": "usd",
                    "ids": ",".join(COINGECKO_IDS.keys()),
                    "price_change_percentage": "24h",
                },
            )
            for coin in markets:
                symbol, coin_name = COINGECKO_IDS.get(
                    coin["id"], (coin["symbol"].upper(), coin["name"])
                )
                quotes.append(
                    AssetQuote(
                        symbol=symbol,
                        name=coin_name,
                        asset_class=AssetClass.CRYPTO,
                        price=coin["current_price"],
                        change_24h=coin.get("price_change_24h"),
                        change_pct_24h=coin.get("price_change_percentage_24h"),
                        market_cap=coin.get("market_cap"),
                        volume_24h=coin.get("total_volume"),
                        source=self.name,
                        extra={"unit": "usd", "circulating_supply": coin.get("circulating_supply")},
                    )
                )

            global_data = (await self._get(client, "/global", {}))["data"]
            total_market_cap = global_data["total_market_cap"]["usd"]
            market_cap_change_pct = global_data.get("market_cap_change_percentage_24h_usd")
            btc_dominance = global_data["market_cap_percentage"]["btc"]

            quotes.append(
                AssetQuote(
                    symbol="TOTAL",
                    name="Total Crypto Market Cap",
                    asset_class=AssetClass.CRYPTO,
                    price=total_market_cap,
                    change_pct_24h=market_cap_change_pct,
                    market_cap=total_market_cap,
                    source=self.name,
                    extra={"unit": "usd"},
                )
            )
            quotes.append(
                AssetQuote(
                    symbol="BTC.D",
                    name="Bitcoin Dominance",
                    asset_class=AssetClass.CRYPTO,
                    price=btc_dominance,
                    source=self.name,
                    extra={"unit": "percent"},
                )
            )
        return quotes
