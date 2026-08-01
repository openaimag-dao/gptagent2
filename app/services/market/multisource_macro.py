"""DXY / Gold / Silver via a fallback chain: Twelve Data -> the existing
yfinance path -> honestly missing. Replaces YFinanceMacroProvider in the
aggregator's default provider list. VIX/US10Y/US30Y/Oil/FedRate are
intentionally left on FredMacroProvider (app/services/market/macro/fred.py,
unchanged) -- FRED is an official, keyed, non-scraped source that's
already reliable when FRED_API_KEY is configured, so routing it through a
scraped/rate-limited chain as well would be a downgrade, not a fix.

Twelve Data's free "Basic" plan is 8 credits/minute, and a multi-symbol
/quote call costs one credit per symbol (confirmed via their pricing docs).
MultiSourceStockProvider's own /quote call already requests 11 symbols (11
credits) -- over the per-minute cap by itself -- and MarketDataAggregator
runs every provider concurrently via asyncio.gather, so this provider's
3-credit macro call was firing in the exact same instant as that 11-credit
stocks call every 5-minute cycle, both landing in the same rate-limit
window and both getting rejected with 429 together (confirmed in
production logs: every single cycle, both calls 429 in the same second).
3 credits alone is well under the 8/minute cap, so `_STAGGER_DELAY_SECONDS`
below deliberately pushes this provider's Twelve Data attempt into the next
minute, clear of the stocks provider's request -- only on an actual cache
miss (never on a cache hit, so once Twelve Data succeeds this delay is
skipped entirely for the following hour via `_TWELVEDATA_TTL_SECONDS`).
"""

import asyncio
import logging

from app.database.redis import get_redis
from app.services.market.base import MarketDataProvider
from app.services.market.macro.yfinance_macro import MACRO_TICKERS
from app.services.market.providers.cache import RedisCooldownCache
from app.services.market.providers.twelvedata import MACRO_SYMBOLS as TD_MACRO_SYMBOLS
from app.services.market.providers.twelvedata import TwelveDataClient, TwelveDataError
from app.services.market.schemas import AssetClass, AssetQuote
from app.services.market.yfinance_utils import download_last_two_closes

logger = logging.getLogger(__name__)

_TWELVEDATA_TTL_SECONDS = 3600  # 3 symbols x 24/day = 72 credits/day
# > 60s so this always crosses into a fresh per-minute credit window,
# regardless of exactly when in the previous minute the stocks provider's
# concurrent call landed.
_STAGGER_DELAY_SECONDS = 70

Bar = tuple[float, float, float | None]

_SYMBOL_INFO: dict[str, tuple[str, str]] = {
    symbol: (name, unit) for _yahoo_ticker, (symbol, name, unit) in MACRO_TICKERS.items()
}
_YAHOO_TICKER_BY_SYMBOL = {symbol: ticker for ticker, (symbol, _, _) in MACRO_TICKERS.items()}


class MultiSourceMacroProvider(MarketDataProvider):
    name = "multisource_macro"

    def __init__(self, twelvedata: TwelveDataClient | None = None) -> None:
        self._twelvedata = twelvedata or TwelveDataClient()
        self._td_cache = RedisCooldownCache(get_redis(), "twelvedata")

    async def _twelvedata_bars(self) -> dict[str, Bar]:
        cached = await self._td_cache.get("macro")
        if cached is not None:
            return {symbol: tuple(bar) for symbol, bar in cached.items()}
        if not self._twelvedata.configured:
            return {}
        await asyncio.sleep(_STAGGER_DELAY_SECONDS)
        try:
            bars = await self._twelvedata.get_quotes(TD_MACRO_SYMBOLS)
        except TwelveDataError as exc:
            logger.warning("Twelve Data macro (DXY/Gold/Silver) fetch failed: %s", exc)
            return {}
        await self._td_cache.set("macro", bars, _TWELVEDATA_TTL_SECONDS)
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
            yahoo_tickers = [_YAHOO_TICKER_BY_SYMBOL[s] for s in missing]
            yahoo_bars = await download_last_two_closes(yahoo_tickers)
            display_by_ticker = {t: s for s, t in _YAHOO_TICKER_BY_SYMBOL.items()}
            for ticker, bar in yahoo_bars.items():
                symbol = display_by_ticker[ticker]
                bars[symbol], sources[symbol] = bar, "yfinance"

        still_missing = sorted(s for s in wanted if s not in bars)
        if still_missing:
            logger.warning(
                "No macro data from any source (Twelve Data, yfinance) for: %s",
                ", ".join(still_missing),
            )
        if sources:
            logger.info(
                "Macro quotes by provider: %s",
                ", ".join(f"{s}={sources[s]}" for s in sorted(sources)),
            )

        quotes: list[AssetQuote] = []
        for symbol, (last_close, prev_close, volume) in bars.items():
            display_name, unit = _SYMBOL_INFO[symbol]
            change = last_close - prev_close
            change_pct = (change / prev_close) * 100 if prev_close else None
            quotes.append(
                AssetQuote(
                    symbol=symbol,
                    name=display_name,
                    asset_class=AssetClass.MACRO,
                    price=last_close,
                    change_24h=change,
                    change_pct_24h=change_pct,
                    volume_24h=volume,
                    source=sources[symbol],
                    extra={"unit": unit, "provider_chain": sources[symbol]},
                )
            )
        return quotes
