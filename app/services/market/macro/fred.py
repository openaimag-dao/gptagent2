import asyncio
import logging
from typing import Any

import httpx

from app.config import get_settings
from app.services.market.base import MarketDataProvider
from app.services.market.schemas import AssetClass, AssetQuote
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"

# FRED series id -> (display symbol, display name, unit)
# These are official daily series, far more reliable from server/datacenter IPs
# than scraping Yahoo Finance, and (being daily closes) no less fresh than the
# daily bars the yfinance-based providers already use.
FRED_SERIES: dict[str, tuple[str, str, str]] = {
    "FEDFUNDS": ("FEDRATE", "US Federal Funds Effective Rate", "percent"),
    "VIXCLS": ("VIX", "CBOE Volatility Index", "index"),
    "DGS10": ("US10Y", "US 10-Year Treasury Yield", "percent"),
    "DGS30": ("US30Y", "US 30-Year Treasury Yield", "percent"),
    "DCOILWTICO": ("OIL", "WTI Crude Oil Spot Price", "usd"),
}


class FredMacroProvider(MarketDataProvider):
    """Fetches Fed Funds Rate, VIX, US10Y, US30Y and WTI Oil from FRED.

    Requires FRED_API_KEY (free: https://fred.stlouisfed.org/docs/api/api_key.html).
    If unset, this provider raises so the aggregator can skip it without
    fabricating any values.
    """

    name = "fred"

    def __init__(self) -> None:
        self._settings = get_settings()

    @default_retry()
    async def _get_observations(
        self, client: httpx.AsyncClient, series_id: str
    ) -> list[dict[str, Any]]:
        response = await client.get(
            FRED_OBSERVATIONS_URL,
            params={
                "series_id": series_id,
                "api_key": self._settings.fred_api_key,
                "file_type": "json",
                "sort_order": "desc",
                "limit": 10,
            },
        )
        response.raise_for_status()
        return response.json()["observations"]

    async def _fetch_series(self, client: httpx.AsyncClient, series_id: str) -> AssetQuote | None:
        symbol, name, unit = FRED_SERIES[series_id]
        try:
            observations = await self._get_observations(client, series_id)
        except Exception:
            logger.warning("FRED series %s failed", series_id, exc_info=True)
            return None

        valid = [obs for obs in observations if obs.get("value") not in (".", None)]
        if not valid:
            logger.warning("FRED series %s returned no usable observations", series_id)
            return None

        latest = valid[0]
        rate = float(latest["value"])
        change = float(latest["value"]) - float(valid[1]["value"]) if len(valid) > 1 else None

        return AssetQuote(
            symbol=symbol,
            name=name,
            asset_class=AssetClass.MACRO,
            price=rate,
            change_24h=change,
            source=self.name,
            extra={"unit": unit, "series_id": series_id, "period": latest["date"]},
        )

    async def fetch(self) -> list[AssetQuote]:
        if not self._settings.fred_api_key:
            raise RuntimeError("FRED_API_KEY is not configured; skipping FRED macro indicators")

        async with build_http_client(self._settings.http_timeout_seconds) as client:
            results = await asyncio.gather(
                *(self._fetch_series(client, series_id) for series_id in FRED_SERIES)
            )

        quotes = [quote for quote in results if quote is not None]
        if not quotes:
            raise RuntimeError("All FRED macro series failed; no data collected")
        return quotes
