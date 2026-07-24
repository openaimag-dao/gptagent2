import enum
from datetime import datetime

from pydantic import BaseModel


class NewsCategory(str, enum.Enum):
    FEDERAL_RESERVE = "federal_reserve"
    SEC = "sec"
    ETF = "etf"
    CRYPTO = "crypto"
    STOCKS = "stocks"
    MACRO = "macro"


class Sentiment(str, enum.Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class RawNewsItem(BaseModel):
    """A single news item as fetched from a source, before classification."""

    title: str
    url: str
    source: str
    category: NewsCategory
    summary: str | None = None
    published_at: datetime | None = None


class ClassifiedNewsItem(RawNewsItem):
    """A RawNewsItem with a sentiment label attached."""

    sentiment: Sentiment
    sentiment_score: float
