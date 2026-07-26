"""Alpha Vantage client -- second fallback for Magnificent 7 stock quotes
(after Twelve Data), and a fallback news-sentiment source when the RSS
News Engine returns nothing for a cycle.

Free tier: 5 requests/minute, 25 requests/day total across ALL functions
(quotes + news share the same daily budget). GLOBAL_QUOTE has no batch
mode, so `get_quotes()` calls it once per symbol with a 12s spacing to
stay under 5/min -- callers should gate how often this whole client runs
via RedisCooldownCache rather than relying on this spacing alone, since
the spacing only protects a single call to `get_quotes()`, not repeated
calls across scheduler ticks.

Alpha Vantage's GLOBAL_QUOTE only covers real listed tickers (stocks/ETFs),
not market indices -- there is no honest Alpha Vantage substitute for
NASDAQ/SPX/DJI/RUT without silently swapping in a proxy ETF price (SPY for
SPX, etc.), which would misrepresent what the number means. This client
therefore only offers the Magnificent 7 as a stock fallback, not indices.

Response shapes below match Alpha Vantage's stable, long-documented
GLOBAL_QUOTE and NEWS_SENTIMENT contracts; only reachability (not real
authenticated data) could be confirmed while building this without a real
API key -- see check_providers.py to verify against a real key.
"""

import asyncio
import logging

import httpx

from app.config import get_settings
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

ALPHAVANTAGE_URL = "https://www.alphavantage.co/query"
_INTER_CALL_DELAY_SECONDS = 12.0  # 5 requests/minute free-tier limit


class AlphaVantageError(RuntimeError):
    pass


class AlphaVantageClient:
    def __init__(self) -> None:
        self._settings = get_settings()

    @property
    def configured(self) -> bool:
        return bool(self._settings.alphavantage_api_key)

    @default_retry()
    async def _get(self, client: httpx.AsyncClient, params: dict) -> dict:
        response = await client.get(
            ALPHAVANTAGE_URL, params={**params, "apikey": self._settings.alphavantage_api_key}
        )
        response.raise_for_status()
        return response.json()

    async def _get_one_quote(
        self, client: httpx.AsyncClient, symbol: str
    ) -> tuple[float, float, float | None] | None:
        try:
            payload = await self._get(client, {"function": "GLOBAL_QUOTE", "symbol": symbol})
        except httpx.HTTPError:
            logger.warning(
                "Alpha Vantage GLOBAL_QUOTE request failed for %s", symbol, exc_info=True
            )
            return None

        quote = payload.get("Global Quote")
        if not quote or "05. price" not in quote:
            logger.warning("Alpha Vantage: no usable quote for %s (%s)", symbol, payload)
            return None
        try:
            price = float(quote["05. price"])
            previous_close = float(quote["08. previous close"])
            volume = float(quote["06. volume"]) if quote.get("06. volume") else None
        except (KeyError, TypeError, ValueError):
            logger.warning("Alpha Vantage: malformed quote for %s", symbol)
            return None
        return price, previous_close, volume

    async def get_quotes(self, symbols: list[str]) -> dict[str, tuple[float, float, float | None]]:
        """Sequential, rate-limit-respecting GLOBAL_QUOTE calls. Returns
        whatever symbols succeeded; never raises for a single bad symbol."""
        if not self.configured:
            raise AlphaVantageError("ALPHAVANTAGE_API_KEY is not configured")
        if not symbols:
            return {}

        results: dict[str, tuple[float, float, float | None]] = {}
        async with build_http_client(self._settings.http_timeout_seconds) as client:
            for index, symbol in enumerate(symbols):
                if index > 0:
                    await asyncio.sleep(_INTER_CALL_DELAY_SECONDS)
                bar = await self._get_one_quote(client, symbol)
                if bar is not None:
                    results[symbol] = bar

        if not results:
            raise AlphaVantageError("Alpha Vantage returned no usable quotes for any symbol")
        return results

    async def get_news_sentiment(
        self, topics: str = "financial_markets", limit: int = 20
    ) -> list[dict] | None:
        """Returns a list of {"title", "url", "sentiment_score" (-1..1),
        "sentiment_label"} items, or None if unavailable. `sentiment_score`
        is Alpha Vantage's own model output, not re-derived by this project's
        lexicon classifier."""
        if not self.configured:
            return None

        async with build_http_client(self._settings.http_timeout_seconds) as client:
            try:
                payload = await self._get(
                    client,
                    {"function": "NEWS_SENTIMENT", "topics": topics, "limit": str(limit)},
                )
            except httpx.HTTPError:
                logger.warning("Alpha Vantage NEWS_SENTIMENT request failed", exc_info=True)
                return None

        feed = payload.get("feed")
        if not feed:
            logger.warning("Alpha Vantage NEWS_SENTIMENT returned no feed (%s)", payload)
            return None

        items = []
        for entry in feed:
            try:
                items.append(
                    {
                        "title": entry["title"],
                        "url": entry["url"],
                        "sentiment_score": float(entry["overall_sentiment_score"]),
                        "sentiment_label": entry["overall_sentiment_label"],
                    }
                )
            except (KeyError, TypeError, ValueError):
                continue
        return items or None
