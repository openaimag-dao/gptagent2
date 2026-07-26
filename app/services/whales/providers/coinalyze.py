"""Coinalyze client -- second fallback for derivatives-market aggregates
(funding rate, open interest, 24h liquidations) when CoinGlass is
unconfigured or its call fails. Like CoinGlass, Coinalyze is a
derivatives-data aggregator, not an on-chain wallet tracker -- it cannot
supply exchange netflow, large-wallet accumulation, or stablecoin supply
changes, and it does not offer a long/short ratio endpoint on its free
tier, so this client never claims those fields.

Auth is an `api_key` header. Symbols use Coinalyze's exchange-suffixed
instrument codes (e.g. "BTCUSDT_PERP.A" = Binance perpetual); this client
defaults to the Binance perpetual for whichever coin is requested.

Response shapes below follow Coinalyze's documented v1 contract; only
reachability (HTTP 401 without a key) could be confirmed while building
this without a real API key -- run check_providers.py with a real
COINALYZE_API_KEY to confirm parsing.
"""

import logging
import time

import httpx

from app.config import get_settings
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

COINALYZE_BASE_URL = "https://api.coinalyze.net/v1"
_LIQUIDATION_LOOKBACK_SECONDS = 24 * 3600


class CoinalyzeError(RuntimeError):
    pass


def _instrument(symbol: str) -> str:
    return f"{symbol.upper()}USDT_PERP.A"


def _first_value(payload: object, instrument: str) -> float | None:
    if not isinstance(payload, list):
        return None
    for entry in payload:
        if isinstance(entry, dict) and entry.get("symbol") == instrument:
            value = entry.get("value")
            try:
                return float(value)
            except (TypeError, ValueError):
                return None
    return None


class CoinalyzeClient:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def configured(self) -> bool:
        return bool(self._settings.coinalyze_api_key)

    @default_retry()
    async def _get(self, client: httpx.AsyncClient, path: str, params: dict) -> object:
        response = await client.get(
            f"{COINALYZE_BASE_URL}{path}",
            params=params,
            headers={"api_key": self._settings.coinalyze_api_key},
        )
        response.raise_for_status()
        return response.json()

    async def get_snapshot(self, symbol: str = "BTC") -> dict[str, float]:
        """Returns whatever of {funding_rate, open_interest,
        liquidations_24h} Coinalyze has for `symbol`. Never fabricates a
        long_short_ratio -- Coinalyze doesn't offer one on the free tier."""
        if not self.configured:
            raise CoinalyzeError("COINALYZE_API_KEY is not configured")

        instrument = _instrument(symbol)
        result: dict[str, float] = {}
        async with build_http_client(self._settings.http_timeout_seconds) as client:
            try:
                oi = await self._get(client, "/open-interest", {"symbols": instrument})
                value = _first_value(oi, instrument)
                if value is not None:
                    result["open_interest"] = value
            except httpx.HTTPError as exc:
                logger.warning("Coinalyze open interest fetch failed for %s: %s", symbol, exc)

            try:
                funding = await self._get(client, "/funding-rate", {"symbols": instrument})
                value = _first_value(funding, instrument)
                if value is not None:
                    result["funding_rate"] = value
            except httpx.HTTPError as exc:
                logger.warning("Coinalyze funding rate fetch failed for %s: %s", symbol, exc)

            try:
                now = int(time.time())
                liq = await self._get(
                    client,
                    "/liquidation-history",
                    {
                        "symbols": instrument,
                        "interval": "1hour",
                        "from": now - _LIQUIDATION_LOOKBACK_SECONDS,
                        "to": now,
                    },
                )
                total = _sum_liquidation_history(liq, instrument)
                if total is not None:
                    result["liquidations_24h"] = total
            except httpx.HTTPError as exc:
                logger.warning("Coinalyze liquidations fetch failed for %s: %s", symbol, exc)

        if not result:
            raise CoinalyzeError(f"Coinalyze returned no usable derivatives data for {symbol}")
        return result


def _sum_liquidation_history(payload: object, instrument: str) -> float | None:
    if not isinstance(payload, list):
        return None
    for entry in payload:
        if not isinstance(entry, dict) or entry.get("symbol") != instrument:
            continue
        history = entry.get("history")
        if not isinstance(history, list):
            return None
        total = 0.0
        found = False
        for point in history:
            if not isinstance(point, dict):
                continue
            for key in ("l", "s"):
                value = point.get(key)
                if value is not None:
                    try:
                        total += float(value)
                        found = True
                    except (TypeError, ValueError):
                        continue
        return total if found else None
    return None
