from app.services.market.base import MarketDataProvider
from app.services.market.schemas import AssetClass, AssetQuote
from app.services.market.yfinance_utils import download_last_two_closes

# Yahoo Finance ticker -> (display symbol, display name, unit)
# VIX, US10Y, US30Y, Oil and Fed Rate are sourced from FRED instead (see
# macro/fred.py) since official FRED series are far more reliable from
# server/datacenter IPs than scraping Yahoo Finance. DXY, Gold and Silver
# have no equivalent free official series, so they stay on Yahoo Finance.
MACRO_TICKERS: dict[str, tuple[str, str, str]] = {
    "DX-Y.NYB": ("DXY", "US Dollar Index", "index"),
    "GC=F": ("GOLD", "Gold Futures", "usd"),
    "SI=F": ("SILVER", "Silver Futures", "usd"),
}


class YFinanceMacroProvider(MarketDataProvider):
    """Fetches DXY, Gold and Silver via Yahoo Finance."""

    name = "yfinance_macro"

    async def fetch(self) -> list[AssetQuote]:
        tickers = list(MACRO_TICKERS)
        bars = await download_last_two_closes(tickers)

        quotes: list[AssetQuote] = []
        for ticker, (last_close, prev_close, volume) in bars.items():
            symbol, display_name, unit = MACRO_TICKERS[ticker]

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
                    source=self.name,
                    extra={"unit": unit, "yahoo_ticker": ticker},
                )
            )
        return quotes
