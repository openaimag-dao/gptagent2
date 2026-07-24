from app.services.market.base import MarketDataProvider
from app.services.market.schemas import AssetClass, AssetQuote
from app.services.market.yfinance_utils import download_last_two_closes

# Yahoo Finance ticker -> (display symbol, display name)
INDEX_TICKERS: dict[str, tuple[str, str]] = {
    "^IXIC": ("NASDAQ", "NASDAQ Composite"),
    "^GSPC": ("SPX", "S&P 500"),
    "^DJI": ("DJI", "Dow Jones Industrial Average"),
    "^RUT": ("RUT", "Russell 2000"),
}

MAGNIFICENT_SEVEN: dict[str, str] = {
    "AAPL": "Apple",
    "MSFT": "Microsoft",
    "NVDA": "Nvidia",
    "AMZN": "Amazon",
    "META": "Meta Platforms",
    "GOOGL": "Alphabet (Google)",
    "TSLA": "Tesla",
}


class YFinanceStockProvider(MarketDataProvider):
    """Fetches major US index levels and Magnificent 7 stock quotes via Yahoo Finance."""

    name = "yfinance_stocks"

    async def fetch(self) -> list[AssetQuote]:
        tickers = list(INDEX_TICKERS) + list(MAGNIFICENT_SEVEN)
        bars = await download_last_two_closes(tickers)

        quotes: list[AssetQuote] = []
        for ticker, (last_close, prev_close, volume) in bars.items():
            change = last_close - prev_close
            change_pct = (change / prev_close) * 100 if prev_close else None

            if ticker in INDEX_TICKERS:
                symbol, display_name = INDEX_TICKERS[ticker]
                asset_class = AssetClass.INDEX
            else:
                symbol, display_name = ticker, MAGNIFICENT_SEVEN[ticker]
                asset_class = AssetClass.STOCK

            quotes.append(
                AssetQuote(
                    symbol=symbol,
                    name=display_name,
                    asset_class=asset_class,
                    price=last_close,
                    change_24h=change,
                    change_pct_24h=change_pct,
                    volume_24h=volume,
                    source=self.name,
                    extra={"unit": "usd", "yahoo_ticker": ticker},
                )
            )
        return quotes
