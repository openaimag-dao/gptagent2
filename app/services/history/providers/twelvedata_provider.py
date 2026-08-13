"""Twelve Data historical provider -- fallback for the yfinance-sourced
history backfill (stocks/forex/gold/silver) when yfinance is blocked or
rate-limited, which is confirmed to be happening on this deployment
(Yahoo Finance returning empty/malformed responses from this environment's
egress IP; see AUDIT_REPORT.md). Reuses the same TWELVEDATA_API_KEY already
configured for the live-quote fallback path
(app/services/market/providers/twelvedata.py) -- no new secret.

Live-verified while building this against the free tier (confirmed by
direct API calls, not just documentation):
- Individual equities (AAPL etc.) and spot forex/commodity pairs (EUR/USD,
  XAU/USD, XAG/USD) work via `/time_series` with outputsize=5000, returning
  up to ~20 years of daily bars in a single call.
- Indices (NASDAQ/SPX/DJI/RUT) and the DXY dollar index are NOT available
  on the free tier via this endpoint ("This symbol is available starting
  with the Grow or Venture plan") -- those stay yfinance-only and remain a
  known, documented gap (STOCK_SYMBOLS/MACRO_SYMBOLS below deliberately
  excludes them rather than silently failing on an unmapped symbol).
- Free tier is rate-limited to 8 credits/minute; _pace_request() below
  self-paces calls to stay under that, since a full backfill run issues
  one call per symbol back to back otherwise.

Only daily bars are covered (fetch_candles returns [] for any other
timeframe) -- intraday (1h/4h) history stays yfinance-only, since Twelve
Data's free-tier intraday depth/availability wasn't verified and this
project's backtest/probability/forecast engines all default to daily
anyway.
"""

import asyncio
import logging
from datetime import UTC, datetime

import httpx

from app.config import get_settings
from app.services.history.base import HistoricalDataProvider
from app.services.history.schemas import Candle, Timeframe
from app.services.market.providers.twelvedata import MACRO_SYMBOLS, STOCK_SYMBOLS
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

TIME_SERIES_URL = "https://api.twelvedata.com/time_series"

FOREX_SYMBOLS: dict[str, str] = {
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "USDCHF": "USD/CHF",
    "AUDUSD": "AUD/USD",
    "USDCAD": "USD/CAD",
}

# DXY deliberately excluded from MACRO_SYMBOLS' GOLD/SILVER-only usage here
# -- no working Twelve Data free-tier symbol was found for it (tried DXY,
# DXY:ICE, "US Dollar Index"; only proxy ETFs UUP/UDN exist as tradeable
# instruments, not the index itself).
_SYMBOL_MAP: dict[str, str] = {
    **STOCK_SYMBOLS,
    **FOREX_SYMBOLS,
    "GOLD": MACRO_SYMBOLS["GOLD"],
    "SILVER": MACRO_SYMBOLS["SILVER"],
}

_MIN_CALL_INTERVAL_SECONDS = 8.0
_rate_limit_lock = asyncio.Lock()
_last_call_at: float = 0.0


async def _pace_request() -> None:
    """Module-level (not per-instance) so pacing holds regardless of how
    many provider instances get constructed -- the 8 credits/minute budget
    is per API key, not per object."""
    global _last_call_at
    async with _rate_limit_lock:
        loop = asyncio.get_event_loop()
        wait = _MIN_CALL_INTERVAL_SECONDS - (loop.time() - _last_call_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_at = loop.time()


class TwelveDataHistoricalProvider(HistoricalDataProvider):
    name = "twelvedata_historical"

    def __init__(self) -> None:
        self._settings = get_settings()

    @default_retry()
    async def _get(self, client: httpx.AsyncClient, td_symbol: str) -> dict:
        response = await client.get(
            TIME_SERIES_URL,
            params={
                "symbol": td_symbol,
                "interval": "1day",
                "outputsize": 5000,
                "apikey": self._settings.twelvedata_api_key,
            },
        )
        response.raise_for_status()
        return response.json()

    async def fetch_candles(
        self, symbol: str, timeframe: Timeframe, since: datetime | None
    ) -> list[Candle]:
        if timeframe != Timeframe.DAILY:
            return []
        if not self._settings.twelvedata_api_key:
            return []
        td_symbol = _SYMBOL_MAP.get(symbol.upper())
        if td_symbol is None:
            return []

        await _pace_request()
        async with build_http_client(self._settings.http_timeout_seconds) as client:
            try:
                payload = await self._get(client, td_symbol)
            except httpx.HTTPError as exc:
                logger.warning("Twelve Data historical fetch failed for %s: %s", symbol, exc)
                return []

        if not isinstance(payload, dict) or payload.get("status") != "ok":
            logger.warning(
                "Twelve Data historical: no usable data for %s (%s)",
                symbol,
                payload.get("message") if isinstance(payload, dict) else payload,
            )
            return []

        candles = []
        for row in payload.get("values", []):
            try:
                timestamp = datetime.strptime(row["datetime"], "%Y-%m-%d").replace(tzinfo=UTC)
                candles.append(
                    Candle(
                        symbol=symbol.upper(),
                        timeframe=Timeframe.DAILY,
                        timestamp=timestamp,
                        open=float(row["open"]),
                        high=float(row["high"]),
                        low=float(row["low"]),
                        close=float(row["close"]),
                        volume=(
                            float(row["volume"]) if row.get("volume") not in (None, "") else None
                        ),
                        source=self.name,
                    )
                )
            except (KeyError, ValueError):
                continue

        candles.sort(key=lambda c: c.timestamp)
        if since is not None:
            candles = [c for c in candles if c.timestamp >= since]
        return candles
