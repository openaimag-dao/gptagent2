"""Sentiment Agent -- thin summarizing wrapper around SentimentEngine (the
real Fear & Greed + news-sentiment aggregator). No logic lives here beyond
formatting; the computation is SentimentEngine's alone."""

from app.services.agents.base import AgentOutput
from app.services.sentiment.engine import SentimentEngine


class SentimentAgent:
    def __init__(self, sentiment_engine: SentimentEngine) -> None:
        self._sentiment_engine = sentiment_engine

    async def summarize(self) -> AgentOutput:
        snapshot = await self._sentiment_engine.compute_and_store()

        lines = ["*SENTIMENT SUMMARY*", ""]
        if snapshot.fear_greed_value is not None:
            lines.append(
                f"Fear & Greed Index: {snapshot.fear_greed_value}/100 "
                f"({snapshot.fear_greed_classification})"
            )
        else:
            lines.append("Fear & Greed Index: unavailable this cycle.")
        if snapshot.news_sentiment_score is not None:
            lines.append(f"News sentiment: {snapshot.news_sentiment_score}/100")
        lines.append(f"Social/options sentiment: {snapshot.social_sentiment_reason}")
        if snapshot.global_sentiment_score is not None:
            lines.append("")
            lines.append(f"Global Sentiment Score: {snapshot.global_sentiment_score}/100")

        return AgentOutput(
            agent="sentiment",
            summary="\n".join(lines),
            data={
                "fear_greed_value": snapshot.fear_greed_value,
                "fear_greed_classification": snapshot.fear_greed_classification,
                "news_sentiment_score": snapshot.news_sentiment_score,
                "social_sentiment_available": snapshot.social_sentiment_available,
                "social_sentiment_reason": snapshot.social_sentiment_reason,
                "global_sentiment_score": snapshot.global_sentiment_score,
            },
        )
