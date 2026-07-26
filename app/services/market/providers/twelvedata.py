"""Twelve Data client -- primary fallback source for indices/stocks/DXY/
Gold/Silver when the existing yfinance path is blocked or rate-limited.

Free tier: 800 API credits/day, 1 credit per symbol per call (see
https://twelvedata.com/pricing). Symbol conventions below follow Twelve
Data's documented `/quote` endpoint contract; only the single-symbol shape
(one real ticker, AAPL) could be live-verified against their public "demo"
key while building this -- every other symbol demo-key request 401s
("demo key is for AAPL only"), so batch/forex/index responses are handled
per their documented shape but were not live-verified end to end. Run
check_providers.py with a real TWELVEDATA_API_KEY to confirm.
"""

import logging

import httpx

from app.config import get_settings
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

TWELVEDATA_QUOTE_URL = "https://api.twelvedata.com/quote"

# display symbol -> Twelve Data symbol. Twelve Data uses plain index
# mnemonics (no yfinance-style "^" prefix) and forex-pair notation for
# spot commodities (no yfinance-style "=F" futures suffix).
INDEX_SYMBOLS: dict[str, str] = {
    "NASDAQ": "IXIC",
    "SPX": "SPX",
    "DJI": "DJI",
    "RUT": "RUT",
}
STOCK_SYMBOLS: dict[str, str] = {
    "AAPL": "AAPL",
    "MSFT": "MSFT",
    "NVDA": "NVDA",
    "TSLA": "TSLA",
    "AMZN": "AMZN",
    "META": "META",
    "GOOGL": "GOOGL",
}
MACRO_SYMBOLS: dict[str, str] = {
    "DXY": "DXY",
    "GOLD": "XAU/USD",
    "SILVER": "XAG/USD",
}


class TwelveDataError(RuntimeError):
    pass


class TwelveDataClient:
    """Wraps Twelve Data's /quote endpoint, normalizing both its
    single-symbol (flat dict) and multi-symbol ({symbol: dict}) response
    shapes into {display_symbol: (last_close, previous_close, volume)}."""

    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def configured(self) -> bool:
        return bool(self._settings.twelvedata_api_key)

    @default_retry()
    async def _get(self, client: httpx.AsyncClient, td_symbols: list[str]) -> dict:
        response = await client.get(
            TWELVEDATA_QUOTE_URL,
            params={"symbol": ",".join(td_symbols), "apikey": self._settings.twelvedata_api_key},
        )
        response.raise_for_status()
        return response.json()

    async def get_quotes(
        self, symbol_map: dict[str, str]
    ) -> dict[str, tuple[float, float, float | None]]:
        """`symbol_map` is {display_symbol: twelvedata_symbol}. Returns
        {display_symbol: (last_close, previous_close, volume)} for every
        symbol Twelve Data could price. Raises TwelveDataError if not
        configured, the call itself fails, or nothing came back usable."""
        if not self.configured:
            raise TwelveDataError("TWELVEDATA_API_KEY is not configured")
        if not symbol_map:
            return {}

        td_symbols = list(symbol_map.values())
        async with build_http_client(self._settings.http_timeout_seconds) as client:
            try:
                payload = await self._get(client, td_symbols)
            except httpx.HTTPError as exc:
                raise TwelveDataError(f"Twelve Data request failed: {exc}") from exc

        if isinstance(payload, dict) and payload.get("status") == "error":
            raise TwelveDataError(f"Twelve Data error: {payload.get('message')}")

        # A single-symbol request returns one flat quote dict; a
        # multi-symbol request returns {td_symbol: quote_dict}.
        raw_by_td_symbol = {td_symbols[0]: payload} if len(td_symbols) == 1 else payload

        results: dict[str, tuple[float, float, float | None]] = {}
        display_by_td_symbol = {v: k for k, v in symbol_map.items()}
        for td_symbol, raw in raw_by_td_symbol.items():
            display_symbol = display_by_td_symbol.get(td_symbol)
            if display_symbol is None:
                continue
            if not isinstance(raw, dict) or raw.get("status") == "error" or "close" not in raw:
                logger.warning("Twelve Data: no usable quote for %s (%s)", td_symbol, raw)
                continue
            try:
                last_close = float(raw["close"])
                prev_close = float(raw["previous_close"])
                volume = float(raw["volume"]) if raw.get("volume") not in (None, "") else None
            except (KeyError, TypeError, ValueError):
                logger.warning("Twelve Data: malformed quote for %s", td_symbol)
                continue
            results[display_symbol] = (last_close, prev_close, volume)

        if not results:
            raise TwelveDataError("Twelve Data returned no usable quotes for any requested symbol")
        return results
