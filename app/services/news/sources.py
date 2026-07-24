from app.services.news.base import NewsSource
from app.services.news.rss_source import RSSNewsSource
from app.services.news.schemas import NewsCategory


def default_news_sources() -> list[NewsSource]:
    return [
        RSSNewsSource(
            "federal_reserve",
            "https://www.federalreserve.gov/feeds/press_all.xml",
            NewsCategory.FEDERAL_RESERVE,
        ),
        RSSNewsSource(
            "sec",
            "https://www.sec.gov/news/pressreleases.rss",
            NewsCategory.SEC,
        ),
        RSSNewsSource(
            "etfdb",
            "https://etfdb.com/feed/",
            NewsCategory.ETF,
        ),
        RSSNewsSource(
            "coindesk",
            "https://www.coindesk.com/arc/outboundfeeds/rss/",
            NewsCategory.CRYPTO,
        ),
        RSSNewsSource(
            "cointelegraph",
            "https://cointelegraph.com/rss",
            NewsCategory.CRYPTO,
        ),
        RSSNewsSource(
            "cnbc_top_news",
            "https://www.cnbc.com/id/100003114/device/rss/rss.html",
            NewsCategory.STOCKS,
        ),
        RSSNewsSource(
            "investing_stocks",
            "https://www.investing.com/rss/news_25.rss",
            NewsCategory.STOCKS,
        ),
        RSSNewsSource(
            "investing_economy",
            "https://www.investing.com/rss/news_14.rss",
            NewsCategory.MACRO,
        ),
    ]
