"""CoinGlass client -- primary source for derivatives-market aggregates
(funding rate, open interest, 24h liquidations, long/short ratio) used by
WhaleIntelligenceEngine. CoinGlass is a derivatives-data aggregator, not an
on-chain wallet tracker -- it cannot supply exchange netflow, large-wallet
accumulation, or stablecoin supply changes, so this client never claims
those fields.

Auth is a `CG-API-KEY` header (CoinGlass v3 Open API). Endpoints used:
- `/api/futures/coins-markets` -- per-coin aggregated funding rate, open
  interest and long/short ratio in a single call.
- `/api/futures/liquidation/coin-list` -- per-coin 24h liquidation totals.

Response shapes below follow CoinGlass's documented v3 contract; only
reachability (HTTP 200 with an auth-error envelope) could be confirmed
while building this without a real API key -- field names are matched
defensively against several plausible spellings, and any field CoinGlass
doesn't return in the shape expected is simply left out rather than
guessed. Run check_providers.py with a real COINGLASS_API_KEY to confirm
parsing and adjust the candidate field names below if CoinGlass's actual
response differs.
"""

import logging

import httpx

from app.config import get_settings
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

COINGLASS_BASE_URL = "https://open-api-v3.coinglass.com"

_FUNDING_RATE_KEYS = ("fundingRate", "rate", "funding_rate")
_OPEN_INTEREST_KEYS = ("openInterest", "openInterestAmount", "open_interest_usd")
_LONG_SHORT_RATIO_KEYS = ("longShortRatio", "longShortAccountRatio", "ratio")
_LIQUIDATION_24H_KEYS = ("liquidationUsd24h", "h24LiquidationUsd", "liquidation24h")


class CoinGlassError(RuntimeError):
    pass


def _find_entry_for_symbol(payload: object, symbol: str) -> dict | None:
    data = payload.get("data") if isinstance(payload, dict) else None
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return None
    for entry in data:
        if not isinstance(entry, dict):
            continue
        entry_symbol = str(entry.get("symbol") or entry.get("baseAsset") or "").upper()
        if entry_symbol == symbol.upper():
            return entry
    return None


def _first_numeric(entry: dict, keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = entry.get(key)
        if value in (None, ""):
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


class CoinGlassClient:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def configured(self) -> bool:
        return bool(self._settings.coinglass_api_key)

    @default_retry()
    async def _get(self, client: httpx.AsyncClient, path: str, params: dict) -> dict:
        response = await client.get(
            f"{COINGLASS_BASE_URL}{path}",
            params=params,
            headers={"CG-API-KEY": self._settings.coinglass_api_key},
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("success") is False:
            raise CoinGlassError(f"CoinGlass error: {payload.get('msg')}")
        return payload

    async def get_snapshot(self, symbol: str = "BTC") -> dict[str, float]:
        """Returns whatever of {funding_rate, open_interest,
        long_short_ratio, liquidations_24h} CoinGlass has for `symbol`.
        Fields it doesn't return (or returns in an unrecognized shape) are
        simply absent -- never fabricated or defaulted."""
        if not self.configured:
            raise CoinGlassError("COINGLASS_API_KEY is not configured")

        result: dict[str, float] = {}
        async with build_http_client(self._settings.http_timeout_seconds) as client:
            try:
                markets = await self._get(client, "/api/futures/coins-markets", {})
                entry = _find_entry_for_symbol(markets, symbol)
                if entry is not None:
                    funding = _first_numeric(entry, _FUNDING_RATE_KEYS)
                    if funding is not None:
                        result["funding_rate"] = funding
                    open_interest = _first_numeric(entry, _OPEN_INTEREST_KEYS)
                    if open_interest is not None:
                        result["open_interest"] = open_interest
                    ratio = _first_numeric(entry, _LONG_SHORT_RATIO_KEYS)
                    if ratio is not None:
                        result["long_short_ratio"] = ratio
                else:
                    logger.warning("CoinGlass coins-markets: no entry found for %s", symbol)
            except (httpx.HTTPError, CoinGlassError) as exc:
                logger.warning("CoinGlass coins-markets fetch failed for %s: %s", symbol, exc)

            try:
                liquidations = await self._get(client, "/api/futures/liquidation/coin-list", {})
                entry = _find_entry_for_symbol(liquidations, symbol)
                if entry is not None:
                    liq_24h = _first_numeric(entry, _LIQUIDATION_24H_KEYS)
                    if liq_24h is not None:
                        result["liquidations_24h"] = liq_24h
                else:
                    logger.warning("CoinGlass liquidation/coin-list: no entry for %s", symbol)
            except (httpx.HTTPError, CoinGlassError) as exc:
                logger.warning("CoinGlass liquidations fetch failed for %s: %s", symbol, exc)

        if not result:
            raise CoinGlassError(f"CoinGlass returned no usable derivatives data for {symbol}")
        return result
