import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import get_settings
from app.services.history.base import HistoricalDataProvider
from app.services.history.resample import resample_candles
from app.services.history.schemas import Candle, Timeframe
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

# symbol -> CoinGecko coin id
COINGECKO_SYMBOL_IDS: dict[str, str] = {
    "BTC": "bitcoin",
    "ETH": "ethereum",
    "SOL": "solana",
    "LINK": "chainlink",
    "UNI": "uniswap",
    # Futures Simulator (Phase 4): added to cover the simulator's full
    # 10-symbol supported-asset list -- same provider, no new integration.
    "BNB": "binancecoin",
    "XRP": "ripple",
    "DOGE": "dogecoin",
    "AVAX": "avalanche-2",
    "SUI": "sui",
}

# CoinGecko's free/demo API has no `interval` override (that's Enterprise-plan
# only); it auto-selects granularity by the requested day range: 1 day ->
# 5-minutely, 2-90 days -> hourly, above 90 days -> daily. We pick `days` to
# land on the granularity we want rather than requesting it directly.
#
# `days=max` (or any range past 365 days) 401s for every free/"Demo"-plan
# caller -- keyed or not -- with "Public API users are limited to querying
# historical data within the past 365 days" (live-verified; this is a
# CoinGecko-side policy change, not a bug in this client). 365 days is the
# most this engine can honestly backfill for BTC/ETH/SOL without a paid
# CoinGecko plan.
_DAILY_DAYS = 365
_HOURLY_WINDOW_DAYS = 90


class CoinGeckoHistoricalProvider(HistoricalDataProvider):
    """Historical daily/hourly candles for BTC, ETH and SOL from CoinGecko.

    CoinGecko's free API has no historical endpoint for TOTAL market cap or
    BTC dominance (only the live `/global` snapshot), so those two symbols
    are intentionally not backfillable here -- see README for the documented
    limitation, mirroring how the live-snapshot yfinance limitation is
    already documented for this project.

    `/market_chart` returns one price point per timestamp, not true OHLC, so
    open/high/low/close are all set to that price -- the same adaptation
    used for single-value FRED series (see providers/fred.py).
    """

    name = "coingecko_historical"

    def __init__(self) -> None:
        self._settings = get_settings()

    def _headers(self) -> dict[str, str]:
        if self._settings.coingecko_api_key:
            return {"x-cg-demo-api-key": self._settings.coingecko_api_key}
        return {}

    @default_retry()
    async def _get_market_chart(
        self, client: httpx.AsyncClient, coin_id: str, days: str | int
    ) -> dict[str, Any]:
        response = await client.get(
            f"{self._settings.coingecko_base_url}/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": days},
            headers=self._headers(),
        )
        response.raise_for_status()
        return response.json()

    async def fetch_candles(
        self, symbol: str, timeframe: Timeframe, since: datetime | None
    ) -> list[Candle]:
        coin_id = COINGECKO_SYMBOL_IDS.get(symbol.upper())
        if coin_id is None:
            raise ValueError(f"No CoinGecko id mapped for symbol {symbol}")

        if timeframe == Timeframe.DAILY:
            days: str | int = _DAILY_DAYS
        elif timeframe in (Timeframe.ONE_HOUR, Timeframe.FOUR_HOUR):
            days = _HOURLY_WINDOW_DAYS
        else:
            raise ValueError(f"Unsupported timeframe {timeframe}")

        async with build_http_client(self._settings.http_timeout_seconds) as client:
            payload = await self._get_market_chart(client, coin_id, days)

        prices: list[list[float]] = payload.get("prices", [])
        volumes: dict[float, float] = dict(payload.get("total_volumes", []))

        candles = [
            Candle(
                symbol=symbol.upper(),
                timeframe=Timeframe.ONE_HOUR if timeframe == Timeframe.FOUR_HOUR else timeframe,
                timestamp=datetime.fromtimestamp(ts_ms / 1000, tz=UTC),
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volumes.get(ts_ms),
                source=self.name,
            )
            for ts_ms, price in prices
        ]

        if timeframe == Timeframe.FOUR_HOUR:
            candles = resample_candles(candles, Timeframe.FOUR_HOUR)

        if since is not None:
            candles = [c for c in candles if c.timestamp >= since]
        return candles
