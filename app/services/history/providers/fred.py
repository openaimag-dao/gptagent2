import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.config import get_settings
from app.services.history.base import HistoricalDataProvider
from app.services.history.schemas import Candle, Timeframe
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

FRED_OBSERVATIONS_URL = "https://api.stlouisfed.org/fred/series/observations"

# symbol -> FRED series id. All daily-or-lower frequency official series --
# FRED has no intraday data at all, so this provider only ever supports
# Timeframe.DAILY (see registry.py, which never requests 4h/1h for these
# symbols in the first place).
FRED_SERIES: dict[str, str] = {
    "FEDRATE": "FEDFUNDS",
    "VIX": "VIXCLS",
    "US10Y": "DGS10",
    "US30Y": "DGS30",
    "OIL": "DCOILWTICO",
    "CPI": "CPIAUCSL",
    "M2": "M2SL",
}


class FredHistoricalProvider(HistoricalDataProvider):
    """Historical daily/monthly observations for FRED-sourced macro series.

    Each observation is a single value (rate, index level, dollar amount),
    not true OHLC -- open/high/low/close are all set to that value, the same
    adaptation used for CoinGecko's `/market_chart` (see providers/coingecko.py).
    """

    name = "fred_historical"

    def __init__(self) -> None:
        self._settings = get_settings()

    @default_retry()
    async def _get_observations(
        self, client: httpx.AsyncClient, series_id: str, since: datetime | None
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {
            "series_id": series_id,
            "api_key": self._settings.fred_api_key,
            "file_type": "json",
            "sort_order": "asc",
            "limit": 100_000,
        }
        if since is not None:
            params["observation_start"] = since.date().isoformat()
        response = await client.get(FRED_OBSERVATIONS_URL, params=params)
        response.raise_for_status()
        return response.json()["observations"]

    async def fetch_candles(
        self, symbol: str, timeframe: Timeframe, since: datetime | None
    ) -> list[Candle]:
        if timeframe != Timeframe.DAILY:
            return []
        if not self._settings.fred_api_key:
            raise RuntimeError("FRED_API_KEY is not configured; cannot backfill FRED history")

        series_id = FRED_SERIES[symbol.upper()]
        async with build_http_client(self._settings.http_timeout_seconds) as client:
            observations = await self._get_observations(client, series_id, since)

        candles = []
        for obs in observations:
            if obs.get("value") in (".", None):
                continue
            value = float(obs["value"])
            candles.append(
                Candle(
                    symbol=symbol.upper(),
                    timeframe=Timeframe.DAILY,
                    timestamp=datetime.fromisoformat(obs["date"]).replace(tzinfo=UTC),
                    open=value,
                    high=value,
                    low=value,
                    close=value,
                    volume=None,
                    source=self.name,
                )
            )
        return candles
