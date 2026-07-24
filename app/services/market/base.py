from abc import ABC, abstractmethod

from app.services.market.schemas import AssetQuote


class MarketDataProvider(ABC):
    """A single data source (CoinGecko, yfinance, FRED, ...) that yields a batch of AssetQuotes."""

    name: str

    @abstractmethod
    async def fetch(self) -> list[AssetQuote]:
        raise NotImplementedError
