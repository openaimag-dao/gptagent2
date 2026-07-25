"""Whale Intelligence.

Exchange inflow/outflow, large-wallet tracking, funding rate, open interest,
liquidations, long/short ratio and stablecoin supply all require a paid,
specialized on-chain/derivatives data source (e.g. Glassnode, CryptoQuant,
Coinglass) -- none is configured anywhere in this project, and there is no
free equivalent with acceptable reliability. Consistent with this project's
rule of never fabricating data (the same rule that keeps
`FredMacroProvider` from inventing a Fed Funds Rate when `FRED_API_KEY` is
unset), this engine reports honestly that it is unavailable rather than
inventing accumulation/distribution numbers. Setting `WHALE_API_KEY` is the
integration point for wiring in a real provider later -- the response shape
below is what that provider would need to fill in.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import WhaleSnapshot

logger = logging.getLogger(__name__)

_RESPONSE_FIELDS = (
    "exchange_netflow",
    "large_wallet_change",
    "funding_rate",
    "open_interest",
    "liquidations_24h",
    "long_short_ratio",
    "stablecoin_supply_change",
    "classification",  # one of: accumulation, distribution, retail_panic, institutional_buying
)


class WhaleIntelligenceEngine:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession] | None = None
    ) -> None:
        self._settings = get_settings()
        self._session_factory = session_factory

    async def get_snapshot(self, symbol: str = "BTC") -> dict:
        if not self._settings.whale_api_key:
            return {
                "available": False,
                "symbol": symbol.upper(),
                "reason": (
                    "WHALE_API_KEY is not configured; on-chain/derivatives data "
                    "(exchange flows, funding rate, open interest, liquidations, "
                    "long/short ratio, stablecoin supply) requires a paid provider "
                    "such as Glassnode, CryptoQuant or Coinglass."
                ),
                "would_return": list(_RESPONSE_FIELDS),
            }

        # No provider is wired up yet even with a key present -- report that
        # honestly too, rather than silently returning nothing useful.
        return {
            "available": False,
            "symbol": symbol.upper(),
            "reason": (
                "WHALE_API_KEY is set, but no whale-data provider is implemented "
                "yet. Add one under app/services/whales/providers/ implementing "
                "this engine's get_snapshot() response shape."
            ),
            "would_return": list(_RESPONSE_FIELDS),
        }

    async def compute_and_store(self, symbol: str = "BTC") -> WhaleSnapshot:
        """Persists the current get_snapshot() read (including an honest
        "unavailable" read) so Market Memory and the Smart Alert Engine have
        real history to compare against. Requires a session_factory."""
        if self._session_factory is None:
            raise RuntimeError("WhaleIntelligenceEngine needs a session_factory to persist")

        snapshot = await self.get_snapshot(symbol)
        row = WhaleSnapshot(
            symbol=symbol.upper(),
            available=snapshot["available"],
            classification=snapshot.get("classification"),
            reason=snapshot.get("reason"),
            data=snapshot,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def get_latest(self, symbol: str = "BTC") -> WhaleSnapshot | None:
        if self._session_factory is None:
            raise RuntimeError("WhaleIntelligenceEngine needs a session_factory to query history")
        async with self._session_factory() as session:
            return await session.scalar(
                select(WhaleSnapshot)
                .where(WhaleSnapshot.symbol == symbol.upper())
                .order_by(WhaleSnapshot.computed_at.desc())
                .limit(1)
            )
