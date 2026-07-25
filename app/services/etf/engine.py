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

from app.database.models import NewsCategory, NewsSentiment
from app.services.news.repository import NewsRepository

logger = logging.getLogger(__name__)

_DEFAULT_WINDOW_HOURS = 72


class ETFIntelligenceEngine:
    def __init__(self, news_repository: NewsRepository) -> None:
        self._news_repository = news_repository

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
