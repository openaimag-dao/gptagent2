"""Thin client for Coinbase Exchange's public WebSocket `ticker` channel.
No API key needed. Chosen over Binance's combined-stream WebSocket (this
project's original realtime source) because Binance.com geo-blocks
datacenter/cloud-hosting IP ranges as a matter of regulatory policy -- this
surfaced as a permanently OFFLINE realtime price feed once actually
deployed (Railway runs on exactly the kind of cloud infrastructure Binance
blocks). Coinbase is a US-licensed exchange with no comparable reason to
block US-origin/cloud traffic.
"""

import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import websockets

from app.services.realtime.schemas import RealtimePriceTick

logger = logging.getLogger(__name__)


def to_coinbase_product(symbol: str) -> str:
    return f"{symbol.strip().upper()}-USD"


class CoinbaseRealtimeClient:
    """One connection covers the whole watchlist -- never one WebSocket per
    symbol. Unlike Binance's combined-stream URL, Coinbase requires an
    explicit subscribe message sent after the connection opens rather than
    encoding the channel list in the URL itself."""

    def __init__(self, ws_url: str, watchlist: list[str]) -> None:
        self._ws_url = ws_url
        self._watchlist = watchlist

    def _subscribe_message(self) -> str:
        return json.dumps(
            {
                "type": "subscribe",
                "product_ids": [to_coinbase_product(symbol) for symbol in self._watchlist],
                "channels": ["ticker"],
            }
        )

    async def stream(self) -> AsyncIterator[RealtimePriceTick]:
        """Connects once, subscribes, and yields ticks until the connection
        drops (the `async with` block raises/exits on disconnect) --
        reconnect/backoff is the collector's responsibility, not this
        client's, so each stays independently testable."""
        async with websockets.connect(self._ws_url, ping_interval=20, ping_timeout=20) as ws:
            await ws.send(self._subscribe_message())
            async for raw in ws:
                tick = parse_ticker_message(raw)
                if tick is not None:
                    yield tick


def parse_ticker_message(raw: str | bytes) -> RealtimePriceTick | None:
    """Pure parse of one Coinbase `ticker` channel message into a
    RealtimePriceTick. Coinbase's ticker payload has no ready-made 24h
    change field (unlike Binance's `p`/`P`) -- change_24h/change_pct_24h
    are derived from the two real fields it does provide (`price` and
    `open_24h`), never fabricated. Returns None (never raises) for any
    non-ticker message (subscription acks, heartbeats, errors) or a
    malformed one, so one bad frame can't kill the whole stream."""
    try:
        payload = json.loads(raw)
        if payload.get("type") != "ticker":
            return None
        price = float(payload["price"])
        open_24h = float(payload["open_24h"]) if payload.get("open_24h") is not None else None
        change_24h = price - open_24h if open_24h is not None else None
        change_pct_24h = (change_24h / open_24h * 100) if open_24h else None
        symbol = str(payload["product_id"]).split("-")[0]
        return RealtimePriceTick(
            symbol=symbol,
            price=price,
            change_24h=change_24h,
            change_pct_24h=change_pct_24h,
            volume_24h=(
                float(payload["volume_24h"]) if payload.get("volume_24h") is not None else None
            ),
            high_24h=float(payload["high_24h"]) if payload.get("high_24h") is not None else None,
            low_24h=float(payload["low_24h"]) if payload.get("low_24h") is not None else None,
            source="coinbase",
            event_timestamp=datetime.fromisoformat(payload["time"]),
            received_at=datetime.now(UTC),
        )
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("Unparseable Coinbase ticker message, skipping: %s", exc)
        return None
