import asyncio
import logging
import uuid
from datetime import UTC, datetime

from app.services.market.base import MarketDataProvider
from app.services.market.crypto.coingecko import CoinGeckoProvider
from app.services.market.macro.fred import FredMacroProvider
from app.services.market.multisource_macro import MultiSourceMacroProvider
from app.services.market.multisource_stocks import MultiSourceStockProvider
from app.services.market.repository import MarketRepository
from app.services.market.schemas import AssetQuote, MarketSnapshotResult

logger = logging.getLogger(__name__)


def default_providers() -> list[MarketDataProvider]:
    return [
        CoinGeckoProvider(),
        MultiSourceStockProvider(),
        MultiSourceMacroProvider(),
        FredMacroProvider(),
    ]


class MarketDataAggregator:
    """Runs every market data provider concurrently and merges the results into one snapshot.

    A single provider failing (rate limit, network blip, missing API key)
    never aborts the whole run -- its error is recorded and collection
    continues with whatever data the other providers returned.
    """

    def __init__(
        self,
        repository: MarketRepository | None,
        providers: list[MarketDataProvider] | None = None,
    ) -> None:
        self._repository = repository
        self._providers = providers if providers is not None else default_providers()

    async def collect(self) -> MarketSnapshotResult:
        results = await asyncio.gather(
            *(provider.fetch() for provider in self._providers),
            return_exceptions=True,
        )

        quotes: list[AssetQuote] = []
        errors: list[str] = []
        for provider, result in zip(self._providers, results):
            if isinstance(result, Exception):
                logger.warning("Provider %s failed: %s", provider.name, result)
                errors.append(f"{provider.name}: {result}")
                continue
            quotes.extend(result)

        if not quotes:
            raise RuntimeError("All market data providers failed; no data collected")

        return MarketSnapshotResult(
            batch_id=uuid.uuid4(),
            collected_at=datetime.now(UTC),
            quotes=quotes,
            errors=errors,
        )

    async def collect_and_store(self) -> MarketSnapshotResult:
        snapshot = await self.collect()
        if self._repository is not None:
            await self._repository.save_batch(snapshot)
        return snapshot
