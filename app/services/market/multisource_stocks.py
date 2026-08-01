"""Indices + Magnificent 7 via a fallback chain: Twelve Data -> Alpha
Vantage (Magnificent 7 only, see providers/alphavantage.py for why
indices are excluded) -> the existing yfinance path -> honestly missing.
Replaces YFinanceStockProvider in the aggregator's default provider list
-- the yfinance path itself is unchanged and still runs as the last
resort, so nothing that used to work stops working.

Twelve Data's free "Basic" plan caps at 8 credits/minute (one credit per
symbol in a /quote call -- confirmed via their pricing docs). The 4 index
symbols (NASDAQ/SPX/DJI/RUT) and 7 Magnificent-7 symbols used to be
requested in a single 11-credit call, which by itself already exceeds the
8/minute cap -- guaranteed to 429 every single cycle regardless of any
other provider's timing (confirmed in production logs: every 5-minute
cycle, 429 for all 11 symbols at once). Splitting into two calls that each
individually fit under the cap (indices=4, Magnificent 7=7), staggered
into separate per-minute windows via `_MAGNIFICENT_SEVEN_DELAY_SECONDS`,
lets each succeed independently. The stagger offset is deliberately
different from MultiSourceMacroProvider's own 70s delay (see
multisource_macro.py) so the two don't land in the same window and
recreate the same 429 (3 macro + 7 stocks = 10 > 8).
"""

import asyncio
import logging

from app.database.redis import get_redis
from app.services.market.base import MarketDataProvider
from app.services.market.providers.alphavantage import AlphaVantageClient, AlphaVantageError
from app.services.market.providers.cache import RedisCooldownCache
from app.services.market.providers.twelvedata import (
    INDEX_SYMBOLS as TD_INDEX_SYMBOLS,
)
from app.services.market.providers.twelvedata import (
    STOCK_SYMBOLS as TD_STOCK_SYMBOLS,
)
from app.services.market.providers.twelvedata import TwelveDataClient, TwelveDataError
from app.services.market.schemas import AssetClass, AssetQuote
from app.services.market.stocks.provider import INDEX_TICKERS, MAGNIFICENT_SEVEN
from app.services.market.yfinance_utils import download_last_two_closes

logger = logging.getLogger(__name__)

# 11 symbols x 24 calls/day (hourly) = 264 credits/day, well under Twelve
# Data's 800/day free-tier budget.
_TWELVEDATA_TTL_SECONDS = 3600
# Clear of MultiSourceMacroProvider's 70s delay (3 credits) so the two
# never share a per-minute window: 7 (Magnificent 7) + 3 (macro) = 10 > 8.
_MAGNIFICENT_SEVEN_DELAY_SECONDS = 140
# Alpha Vantage's 25/day budget is shared with news sentiment (see
# sentiment/engine.py), so this cools down much slower.
_ALPHAVANTAGE_TTL_SECONDS = 7200

Bar = tuple[float, float, float | None]


def _build_symbol_info() -> dict[str, tuple[str, AssetClass]]:
    info: dict[str, tuple[str, AssetClass]] = {}
    for _yahoo_ticker, (display_symbol, name) in INDEX_TICKERS.items():
        info[display_symbol] = (name, AssetClass.INDEX)
    for ticker, name in MAGNIFICENT_SEVEN.items():
        info[ticker] = (name, AssetClass.STOCK)
    return info


_SYMBOL_INFO = _build_symbol_info()
_YAHOO_TICKER_BY_SYMBOL = {s: t for t, (s, _) in INDEX_TICKERS.items()} | {
    t: t for t in MAGNIFICENT_SEVEN
}


class MultiSourceStockProvider(MarketDataProvider):
    name = "multisource_stocks"

    def __init__(
        self,
        twelvedata: TwelveDataClient | None = None,
        alphavantage: AlphaVantageClient | None = None,
    ) -> None:
        self._twelvedata = twelvedata or TwelveDataClient()
        self._alphavantage = alphavantage or AlphaVantageClient()
        redis_client = get_redis()
        self._td_cache = RedisCooldownCache(redis_client, "twelvedata")
        self._av_cache = RedisCooldownCache(redis_client, "alphavantage")

    async def _twelvedata_bars(self) -> dict[str, Bar]:
        """Two independent calls, not one combined 11-credit call -- see
        the module docstring for why (Twelve Data's 8 credits/minute free-
        tier cap)."""
        bars: dict[str, Bar] = {}
        bars.update(await self._twelvedata_indices())
        bars.update(await self._twelvedata_magnificent_seven())
        return bars

    async def _twelvedata_indices(self) -> dict[str, Bar]:
        cached = await self._td_cache.get("stocks_indices")
        if cached is not None:
            return {symbol: tuple(bar) for symbol, bar in cached.items()}
        if not self._twelvedata.configured:
            return {}
        try:
            bars = await self._twelvedata.get_quotes(TD_INDEX_SYMBOLS)
        except TwelveDataError as exc:
            logger.warning("Twelve Data indices fetch failed: %s", exc)
            return {}
        await self._td_cache.set("stocks_indices", bars, _TWELVEDATA_TTL_SECONDS)
        return bars

    async def _twelvedata_magnificent_seven(self) -> dict[str, Bar]:
        cached = await self._td_cache.get("stocks_mag7")
        if cached is not None:
            return {symbol: tuple(bar) for symbol, bar in cached.items()}
        if not self._twelvedata.configured:
            return {}
        # Stagger clear of the indices call above and of
        # MultiSourceMacroProvider's own 70s delay, so this 7-credit
        # request lands in its own per-minute window instead of stacking
        # with either and re-exceeding the 8-credit cap.
        await asyncio.sleep(_MAGNIFICENT_SEVEN_DELAY_SECONDS)
        try:
            bars = await self._twelvedata.get_quotes(TD_STOCK_SYMBOLS)
        except TwelveDataError as exc:
            logger.warning("Twelve Data Magnificent 7 fetch failed: %s", exc)
            return {}
        await self._td_cache.set("stocks_mag7", bars, _TWELVEDATA_TTL_SECONDS)
        return bars

    async def _alphavantage_bars(self, missing: list[str]) -> dict[str, Bar]:
        av_targets = [s for s in missing if s in MAGNIFICENT_SEVEN]
        if not av_targets:
            return {}
        cached = await self._av_cache.get("stocks")
        if cached is not None:
            return {s: tuple(bar) for s, bar in cached.items() if s in av_targets}
        if not self._alphavantage.configured:
            return {}
        try:
            bars = await self._alphavantage.get_quotes(av_targets)
        except AlphaVantageError as exc:
            logger.warning("Alpha Vantage stock fetch failed: %s", exc)
            return {}
        await self._av_cache.set("stocks", bars, _ALPHAVANTAGE_TTL_SECONDS)
        return bars

    async def fetch(self) -> list[AssetQuote]:
        wanted = set(_SYMBOL_INFO)
        bars: dict[str, Bar] = {}
        sources: dict[str, str] = {}

        for symbol, bar in (await self._twelvedata_bars()).items():
            if symbol in wanted:
                bars[symbol], sources[symbol] = bar, "twelvedata"

        missing = [s for s in wanted if s not in bars]
        if missing:
            for symbol, bar in (await self._alphavantage_bars(missing)).items():
                bars[symbol], sources[symbol] = bar, "alphavantage"

        missing = [s for s in wanted if s not in bars]
        if missing:
            yahoo_tickers = [_YAHOO_TICKER_BY_SYMBOL[s] for s in missing]
            yahoo_bars = await download_last_two_closes(yahoo_tickers)
            display_by_ticker = {t: s for s, t in _YAHOO_TICKER_BY_SYMBOL.items()}
            for ticker, bar in yahoo_bars.items():
                symbol = display_by_ticker[ticker]
                bars[symbol], sources[symbol] = bar, "yfinance"

        still_missing = sorted(s for s in wanted if s not in bars)
        if still_missing:
            logger.warning(
                "No stock/index data from any source (Twelve Data, Alpha Vantage, "
                "yfinance) for: %s",
                ", ".join(still_missing),
            )
        if sources:
            logger.info(
                "Stock/index quotes by provider: %s",
                ", ".join(f"{s}={sources[s]}" for s in sorted(sources)),
            )

        quotes: list[AssetQuote] = []
        for symbol, (last_close, prev_close, volume) in bars.items():
            display_name, asset_class = _SYMBOL_INFO[symbol]
            change = last_close - prev_close
            change_pct = (change / prev_close) * 100 if prev_close else None
            quotes.append(
                AssetQuote(
                    symbol=symbol,
                    name=display_name,
                    asset_class=asset_class,
                    price=last_close,
                    change_24h=change,
                    change_pct_24h=change_pct,
                    volume_24h=volume,
                    source=sources[symbol],
                    extra={"unit": "usd", "provider_chain": sources[symbol]},
                )
            )
        return quotes
