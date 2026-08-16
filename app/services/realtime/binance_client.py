"""Thin client for Binance's public combined-stream WebSocket (24hr ticker).
No API key needed and no meaningful rate limit for a handful of symbols --
unlike CoinGecko REST, the sole crypto price source elsewhere in this
codebase, whose free-tier quota is already shared with the 500-symbol
Scanner.
"""

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import websockets

from app.services.realtime.schemas import RealtimePriceTick

logger = logging.getLogger(__name__)


def to_binance_pair(symbol: str) -> str:
    return f"{symbol.strip().lower()}usdt"


class BinanceRealtimeClient:
    """One combined-stream connection covers the whole watchlist -- never
    one WebSocket per symbol."""

    def __init__(self, ws_url: str, watchlist: list[str]) -> None:
        self._base_url = ws_url.rstrip("/")
        self._watchlist = watchlist

    def stream_url(self) -> str:
        streams = "/".join(f"{to_binance_pair(symbol)}@ticker" for symbol in self._watchlist)
        return f"{self._base_url}/stream?streams={streams}"

    async def stream(self) -> AsyncIterator[RealtimePriceTick]:
        """Connects once and yields ticks until the connection drops (the
        `async with` block raises/exits on disconnect) -- reconnect/backoff
        is the collector's responsibility, not this client's, so each stays
        independently testable."""
        async with websockets.connect(self.stream_url(), ping_interval=20, ping_timeout=20) as ws:
            async for raw in ws:
                tick = parse_ticker_message(raw)
                if tick is not None:
                    yield tick


def parse_ticker_message(raw: str | bytes) -> RealtimePriceTick | None:
    """Pure parse of one combined-stream envelope
    (`{"stream": "btcusdt@ticker", "data": {...}}`) into a
    RealtimePriceTick. Returns None (never raises) on a malformed message so
    one bad frame can't kill the whole stream -- logged, not silently
    swallowed."""
    try:
        envelope = json.loads(raw)
        payload = envelope["data"]
        symbol = str(payload["s"]).removesuffix("USDT")
        return RealtimePriceTick(
            symbol=symbol,
            price=float(payload["c"]),
            change_24h=float(payload["p"]) if payload.get("p") is not None else None,
            change_pct_24h=float(payload["P"]) if payload.get("P") is not None else None,
            volume_24h=float(payload["v"]) if payload.get("v") is not None else None,
            high_24h=float(payload["h"]) if payload.get("h") is not None else None,
            low_24h=float(payload["l"]) if payload.get("l") is not None else None,
            source="binance",
            event_timestamp=datetime.fromtimestamp(payload["E"] / 1000, tz=UTC),
            received_at=datetime.now(UTC),
        )
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("Unparseable Binance ticker message, skipping: %s", exc)
        return None
