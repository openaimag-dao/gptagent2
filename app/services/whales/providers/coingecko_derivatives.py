"""CoinGecko derivatives client -- fallback for derivatives-market
aggregates (funding rate, open interest) when CoinGlass is unconfigured or
its call fails. Unlike CoinGlass/Coinalyze, CoinGecko's `/derivatives`
endpoint needs no API key at all (a demo key, if configured, just raises
the rate limit) -- this is a genuinely free, always-available fallback.

CoinGecko is, like CoinGlass, a derivatives-market aggregator, not an
on-chain wallet tracker -- it cannot supply exchange netflow, large-wallet
accumulation, or stablecoin supply changes, and its free `/derivatives`
endpoint has no 24h liquidations or long/short-ratio field, so this client
never claims those.

`/derivatives` returns every tracked perpetual/futures contract across
every exchange in one flat list; there's no per-symbol filter, so this
client fetches the whole list and picks the highest-open-interest
perpetual contract for the requested coin as the most representative read.
"""

import logging

import httpx

from app.config import get_settings
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

_DERIVATIVES_PATH = "/derivatives"


class CoinGeckoDerivativesError(RuntimeError):
    pass


def _headers(coingecko_api_key: str | None) -> dict[str, str]:
    if coingecko_api_key:
        return {"x-cg-demo-api-key": coingecko_api_key}
    return {}


def _best_perpetual(payload: object, symbol: str) -> dict | None:
    if not isinstance(payload, list):
        return None
    candidates = [
        entry
        for entry in payload
        if isinstance(entry, dict)
        and entry.get("index_id") == symbol
        and entry.get("contract_type") == "perpetual"
        and entry.get("open_interest") is not None
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda entry: entry["open_interest"])


class CoinGeckoDerivativesClient:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def configured(self) -> bool:
        # No API key required -- always usable as a fallback.
        return True

    @default_retry()
    async def _get_derivatives(self, client: httpx.AsyncClient) -> object:
        response = await client.get(
            f"{self._settings.coingecko_base_url}{_DERIVATIVES_PATH}",
            headers=_headers(self._settings.coingecko_api_key),
        )
        response.raise_for_status()
        return response.json()

    async def get_snapshot(self, symbol: str = "BTC") -> dict[str, float]:
        """Returns whatever of {funding_rate, open_interest} CoinGecko has
        for `symbol`'s highest-open-interest perpetual contract. Never
        fabricates liquidations_24h or long_short_ratio -- CoinGecko's free
        derivatives endpoint doesn't offer either."""
        symbol = symbol.upper()
        try:
            async with build_http_client(self._settings.http_timeout_seconds) as client:
                payload = await self._get_derivatives(client)
        except httpx.HTTPError as exc:
            raise CoinGeckoDerivativesError(f"CoinGecko derivatives fetch failed: {exc}") from exc

        entry = _best_perpetual(payload, symbol)
        if entry is None:
            raise CoinGeckoDerivativesError(
                f"CoinGecko has no perpetual-contract derivatives data for {symbol}"
            )

        result: dict[str, float] = {}
        funding_rate = entry.get("funding_rate")
        if funding_rate is not None:
            try:
                result["funding_rate"] = float(funding_rate)
            except (TypeError, ValueError):
                pass
        open_interest = entry.get("open_interest")
        if open_interest is not None:
            try:
                result["open_interest"] = float(open_interest)
            except (TypeError, ValueError):
                pass

        if not result:
            raise CoinGeckoDerivativesError(
                f"CoinGecko returned no usable derivatives data for {symbol}"
            )
        return result
