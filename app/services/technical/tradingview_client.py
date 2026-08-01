"""TradingView MCP client -- the "Adapter" layer in TradingView MCP -> Adapter
-> Normalizer -> Provider Layer -> Event Bus -> Existing Engines. No
official public TradingView API exists; this talks to whatever MCP server
is configured at `settings.tradingview_mcp_url` over a documented HTTP
contract (GET {base_url}/indicators?symbol=...&timeframe=... -> JSON).
When unconfigured -- the default, matching every other optional provider
in this project (Twelve Data, CoinGlass, Glassnode, ...) -- `configured`
is False and `fetch_indicators()` short-circuits to None without making a
request, so TechnicalAnalysisProvider falls back to local computation
honestly rather than pretending TradingView answered.
"""

import logging

import httpx

from app.config import get_settings
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 10.0


class TradingViewMCPClient:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def configured(self) -> bool:
        return bool(self._settings.tradingview_mcp_url)

    @default_retry()
    async def _get(self, client: httpx.AsyncClient, symbol: str, timeframe: str) -> dict:
        headers = {}
        if self._settings.tradingview_mcp_api_key:
            headers["Authorization"] = f"Bearer {self._settings.tradingview_mcp_api_key}"
        response = await client.get(
            f"{self._settings.tradingview_mcp_url.rstrip('/')}/indicators",
            params={"symbol": symbol, "timeframe": timeframe},
            headers=headers,
        )
        response.raise_for_status()
        return response.json()

    async def fetch_indicators(self, symbol: str, timeframe: str) -> dict | None:
        """Raw MCP response for one symbol/timeframe, or None if not
        configured or the request ultimately failed after retries."""
        if not self.configured:
            return None
        try:
            async with build_http_client(_TIMEOUT_SECONDS) as client:
                return await self._get(client, symbol, timeframe)
        except Exception:
            logger.warning(
                "TradingView MCP request failed for %s/%s", symbol, timeframe, exc_info=True
            )
            return None
