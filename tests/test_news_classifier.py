from app.services.news.classifier import classify
from app.services.news.schemas import NewsCategory, RawNewsItem, Sentiment


def make_item(title: str, summary: str | None = None) -> RawNewsItem:
    return RawNewsItem(
        title=title,
        url="https://example.com/article",
        source="test",
        category=NewsCategory.CRYPTO,
        summary=summary,
    )


def test_classify_bullish_headline():
    item = make_item("Bitcoin surges to record high as ETF inflows accelerate")

    classified = classify(item)

    assert classified.sentiment is Sentiment.BULLISH
    assert classified.sentiment_score > 0


def test_classify_bearish_headline():
    item = make_item("SEC investigation sends crypto markets into sell-off amid fraud probe")

    classified = classify(item)

    assert classified.sentiment is Sentiment.BEARISH
    assert classified.sentiment_score < 0


def test_classify_neutral_headline():
    item = make_item("Federal Reserve schedules quarterly press conference for next month")

    classified = classify(item)

    assert classified.sentiment is Sentiment.NEUTRAL
    assert classified.sentiment_score == 0


def test_classify_considers_summary_text():
    item = make_item(
        "Weekly market update",
        summary="Stocks rallied and gained sharply as optimism grew across the sector.",
    )

    classified = classify(item)

    assert classified.sentiment is Sentiment.BULLISH
