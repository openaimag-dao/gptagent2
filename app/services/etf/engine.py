"""ETF Intelligence.

Real daily/weekly/monthly ETF creation/redemption dollar-flow data requires
a paid, specialized data source (e.g. Farside Investors, SoSoValue) that is
not configured anywhere in this project. Rather than fabricate a flow
number, this engine surfaces the one real signal already being collected:
aggregate sentiment of ETF-category news (`NewsCategory.ETF`), the same
proxy the Signal Engine's `etf_inflow` factor already relies on (see
`app/services/signals/engine.py`). Every response is explicitly labeled as
a news-sentiment proxy, never presented as confirmed flow data.
"""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import EtfFlowSnapshot, NewsCategory, NewsSentiment
from app.services.news.repository import NewsRepository

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW_HOURS = 72


class ETFIntelligenceEngine:
    def __init__(
        self,
        news_repository: NewsRepository,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._news_repository = news_repository
        self._session_factory = session_factory

    async def get_flow_proxy(
        self, window_hours: int = _DEFAULT_WINDOW_HOURS, limit: int = 50
    ) -> dict:
        since = datetime.now(UTC) - timedelta(hours=window_hours)
        items = await self._news_repository.get_recent(
            category=NewsCategory.ETF.value, limit=limit, since=since
        )

        if not items:
            return {
                "available": False,
                "proxy_only": True,
                "reason": "No ETF-category news collected in this window",
                "items_analyzed": 0,
            }

        bullish = sum(1 for i in items if i.sentiment == NewsSentiment.BULLISH)
        bearish = sum(1 for i in items if i.sentiment == NewsSentiment.BEARISH)
        neutral = len(items) - bullish - bearish
        net = bullish - bearish

        if net > 0:
            classification = "leaning_institutional_buying"
        elif net < 0:
            classification = "leaning_institutional_selling"
        else:
            classification = "neutral"

        return {
            "available": True,
            "proxy_only": True,
            "note": (
                "News-sentiment proxy, not confirmed dollar flow data -- see "
                "docstring for why real ETF flow figures aren't available here."
            ),
            "window_hours": window_hours,
            "items_analyzed": len(items),
            "bullish_items": bullish,
            "bearish_items": bearish,
            "neutral_items": neutral,
            "classification": classification,
            "headlines": [
                {"title": i.title, "sentiment": i.sentiment.value, "url": i.url} for i in items[:10]
            ],
        }

    async def compute_and_store(
        self, window_hours: int = _DEFAULT_WINDOW_HOURS, limit: int = 50
    ) -> EtfFlowSnapshot:
        """Persists the current get_flow_proxy() read so Market Memory and
        the Smart Alert Engine have real history to compare against.
        Requires a session_factory."""
        if self._session_factory is None:
            raise RuntimeError("ETFIntelligenceEngine needs a session_factory to persist")

        proxy = await self.get_flow_proxy(window_hours, limit)
        row = EtfFlowSnapshot(
            available=proxy["available"],
            classification=proxy.get("classification"),
            bullish_items=proxy.get("bullish_items"),
            bearish_items=proxy.get("bearish_items"),
            neutral_items=proxy.get("neutral_items"),
            items_analyzed=proxy.get("items_analyzed", 0),
            window_hours=window_hours,
        )
        async with self._session_factory() as session:
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return row

    async def get_latest(self) -> EtfFlowSnapshot | None:
        if self._session_factory is None:
            raise RuntimeError("ETFIntelligenceEngine needs a session_factory to query history")
        async with self._session_factory() as session:
            return await session.scalar(
                select(EtfFlowSnapshot).order_by(EtfFlowSnapshot.computed_at.desc()).limit(1)
            )
