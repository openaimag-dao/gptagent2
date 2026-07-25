"""News Agent -- collects and classifies crypto/macro/stock/ETF/SEC/Fed
news (already done by the News Engine's deterministic lexicon classifier;
this agent doesn't reclassify anything) and estimates each item's market
impact as a deterministic function of its already-computed sentiment_score
and a per-category weight -- never a fabricated impact figure.
"""

from app.services.agents.base import AgentOutput
from app.services.news.repository import NewsRepository

# Weight applied to |sentiment_score| when estimating market impact: policy
# and flow-moving categories (Fed, SEC, ETF, broad macro) structurally move
# more of the portfolio than a single-asset headline, so they're weighted
# higher. Documented, deterministic, applied uniformly -- not per-item guessing.
_CATEGORY_IMPACT_WEIGHT: dict[str, float] = {
    "federal_reserve": 1.5,
    "sec": 1.2,
    "etf": 1.3,
    "macro": 1.3,
    "crypto": 1.0,
    "stocks": 1.0,
}

_IMPACT_THRESHOLDS = (
    (6.0, "high"),
    (2.0, "medium"),
)


def estimate_impact(sentiment_score: float, category: str) -> str:
    weight = _CATEGORY_IMPACT_WEIGHT.get(category, 1.0)
    weighted = abs(sentiment_score) * weight
    for threshold, label in _IMPACT_THRESHOLDS:
        if weighted >= threshold:
            return label
    return "low"


class NewsAgent:
    def __init__(self, news_repository: NewsRepository, limit: int = 20) -> None:
        self._news_repository = news_repository
        self._limit = limit

    async def summarize(self) -> AgentOutput:
        items = await self._news_repository.get_recent(limit=self._limit)

        by_sentiment = {"bullish": 0, "bearish": 0, "neutral": 0}
        classified_items = []
        for item in items:
            by_sentiment[item.sentiment.value] += 1
            impact = estimate_impact(float(item.sentiment_score), item.category.value)
            classified_items.append(
                {
                    "title": item.title,
                    "category": item.category.value,
                    "sentiment": item.sentiment.value,
                    "impact": impact,
                    "url": item.url,
                }
            )

        lines = ["*NEWS SUMMARY*", ""]
        if not items:
            lines.append("No recent news collected yet.")
        else:
            lines.append(
                f"{len(items)} items: {by_sentiment['bullish']} bullish / "
                f"{by_sentiment['bearish']} bearish / {by_sentiment['neutral']} neutral"
            )
            high_impact = [i for i in classified_items if i["impact"] == "high"]
            if high_impact:
                lines.append("")
                lines.append("High-impact:")
                for i in high_impact[:5]:
                    lines.append(f"- [{i['sentiment']}] {i['title']}")

        return AgentOutput(
            agent="news",
            summary="\n".join(lines),
            data={
                "items_analyzed": len(items),
                "sentiment_counts": by_sentiment,
                "items": classified_items,
            },
        )
