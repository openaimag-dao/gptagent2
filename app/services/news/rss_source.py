import asyncio
import html
import logging
import re
from datetime import UTC, datetime

import feedparser
import httpx

from app.config import get_settings
from app.services.news.base import NewsSource
from app.services.news.schemas import NewsCategory, RawNewsItem
from app.utils.http import build_http_client, default_retry

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _clean_summary(raw: str | None, max_length: int = 400) -> str | None:
    """Strips HTML from an RSS description and truncates it to a clean word boundary."""
    if not raw:
        return None
    text = _WHITESPACE_RE.sub(" ", html.unescape(_TAG_RE.sub("", raw))).strip()
    if not text:
        return None
    if len(text) <= max_length:
        return text
    return text[:max_length].rsplit(" ", 1)[0] + "…"


class RSSNewsSource(NewsSource):
    """Fetches and parses a single RSS/Atom feed. One instance per feed URL."""

    def __init__(self, name: str, feed_url: str, category: NewsCategory) -> None:
        self.name = name
        self.category = category
        self._feed_url = feed_url
        self._settings = get_settings()

    @default_retry()
    async def _download(self, client: httpx.AsyncClient) -> bytes:
        response = await client.get(self._feed_url, follow_redirects=True)
        response.raise_for_status()
        return response.content

    async def fetch(self) -> list[RawNewsItem]:
        async with build_http_client(self._settings.http_timeout_seconds) as client:
            raw_bytes = await self._download(client)

        parsed = await asyncio.to_thread(feedparser.parse, raw_bytes)
        if parsed.bozo and not parsed.entries:
            raise RuntimeError(
                f"Feed {self._feed_url} could not be parsed: {parsed.bozo_exception}"
            )

        items: list[RawNewsItem] = []
        for entry in parsed.entries:
            link = entry.get("link")
            title = entry.get("title")
            if not link or not title:
                continue

            published_at = None
            time_struct = entry.get("published_parsed") or entry.get("updated_parsed")
            if time_struct:
                published_at = datetime(*time_struct[:6], tzinfo=UTC)

            items.append(
                RawNewsItem(
                    title=html.unescape(title).strip(),
                    url=link,
                    source=self.name,
                    category=self.category,
                    summary=_clean_summary(entry.get("summary") or entry.get("description")),
                    published_at=published_at,
                )
            )
        return items
