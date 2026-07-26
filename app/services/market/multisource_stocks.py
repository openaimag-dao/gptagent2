"""Indices + Magnificent 7 via a fallback chain: Twelve Data -> Alpha
Vantage (Magnificent 7 only, see providers/alphavantage.py for why
indices are excluded) -> the existing yfinance path -> honestly missing.
Replaces YFinanceStockProvider in the aggregator's default provider list
-- the yfinance path itself is unchanged and still runs as the last
resort, so nothing that used to work stops working.
"""

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
        cached = await self._td_cache.get("stocks")
        if cached is not None:
            return {symbol: tuple(bar) for symbol, bar in cached.items()}
        if not self._twelvedata.configured:
            return {}
        try:
            bars = await self._twelvedata.get_quotes({**TD_INDEX_SYMBOLS, **TD_STOCK_SYMBOLS})
        except TwelveDataError as exc:
            logger.warning("Twelve Data stocks/indices fetch failed: %s", exc)
            return {}
        await self._td_cache.set("stocks", bars, _TWELVEDATA_TTL_SECONDS)
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
