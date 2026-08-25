"""Futures Simulator chart: aggregates the live Coinbase tick feed
(app/services/realtime/collector.py) into real 5m candles going forward --
100% real observed prices, honestly labeled with their sampling method,
never fabricated or backfilled into history. 15m candles are derived by
resampling three finished 5m candles (app/services/history/resample.py),
never independently aggregated from ticks -- the same "coarser timeframe
derived from a finer one" pattern this codebase already uses for
4h-from-1h, and it guarantees 15m can never drift out of sync with 5m.

Polls once a minute (app/scheduler/jobs.py's
aggregate_realtime_candles_job) rather than subscribing to every tick on
TICKS_CHANNEL -- matches this codebase's existing interval-job
architecture (no other component here is a persistent pub/sub
subscriber). Consequence, documented rather than hidden: a bucket's
recorded `open` can be up to ~60s later than the true bucket start.
Every value is still a real observed price, just coarsely sampled --
never fabricated.
"""

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import CryptoHistory
from app.services.history.repository import fill_missing_indicators, get_series, upsert_candles
from app.services.history.resample import resample_candles
from app.services.history.schemas import Candle, Timeframe
from app.services.realtime.config import parse_watchlist
from app.services.realtime.schemas import RealtimePriceTick
from app.services.realtime.store import get_latest_ticks

logger = logging.getLogger(__name__)

CANDLE_KEY_PREFIX = "realtime:candle:5m:"
_SOURCE = "realtime_coinbase_1m_sampled"


def _floor_to_minutes(ts: datetime, minutes: int) -> datetime:
    floored_minute = (ts.minute // minutes) * minutes
    return ts.replace(minute=floored_minute, second=0, microsecond=0)


def bucket_start(ts: datetime) -> datetime:
    """Floors a timestamp to its 5-minute bucket boundary (UTC)."""
    return _floor_to_minutes(ts, 5)


@dataclass
class BucketState:
    """One symbol's in-progress 5m candle -- persisted to Redis between
    aggregation passes so a process restart resumes it (see module
    docstring) instead of discarding already-observed high/low."""

    bucket_start: datetime
    open: float
    high: float
    low: float
    close: float
    tick_count: int
    first_tick_at: datetime
    last_tick_at: datetime

    def to_json(self) -> str:
        return json.dumps(
            {
                "bucket_start": self.bucket_start.isoformat(),
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "close": self.close,
                "tick_count": self.tick_count,
                "first_tick_at": self.first_tick_at.isoformat(),
                "last_tick_at": self.last_tick_at.isoformat(),
            }
        )

    @classmethod
    def from_json(cls, raw: str) -> "BucketState":
        data = json.loads(raw)
        return cls(
            bucket_start=datetime.fromisoformat(data["bucket_start"]),
            open=data["open"],
            high=data["high"],
            low=data["low"],
            close=data["close"],
            tick_count=data["tick_count"],
            first_tick_at=datetime.fromisoformat(data["first_tick_at"]),
            last_tick_at=datetime.fromisoformat(data["last_tick_at"]),
        )

    @classmethod
    def start(cls, bucket: datetime, tick: RealtimePriceTick) -> "BucketState":
        return cls(
            bucket_start=bucket,
            open=tick.price,
            high=tick.price,
            low=tick.price,
            close=tick.price,
            tick_count=1,
            first_tick_at=tick.event_timestamp,
            last_tick_at=tick.event_timestamp,
        )

    def extend(self, tick: RealtimePriceTick) -> None:
        self.high = max(self.high, tick.price)
        self.low = min(self.low, tick.price)
        self.close = tick.price
        self.tick_count += 1
        self.last_tick_at = tick.event_timestamp

    def to_candle(self, symbol: str) -> Candle:
        return Candle(
            symbol=symbol,
            timeframe=Timeframe.FIVE_MINUTE,
            timestamp=self.bucket_start,
            open=self.open,
            high=self.high,
            low=self.low,
            close=self.close,
            # RealtimePriceTick only carries a rolling 24h volume figure,
            # not per-trade size -- there is no honest way to derive a
            # 5-minute volume from that, so this is left None, never guessed.
            volume=None,
            source=_SOURCE,
        )


async def aggregate_five_minute_candles(
    session_factory: async_sessionmaker[AsyncSession], redis: Redis
) -> list[str]:
    """One aggregation pass: extends or rolls over each watched symbol's
    in-progress 5m bucket from its current live tick, and persists any
    buckets that just finished (plus a 15m roll-up for the symbols that
    got a new 5m candle). Returns the symbols that had a candle finalized
    this pass."""
    settings = get_settings()
    if not settings.realtime_enabled:
        return []

    watchlist = parse_watchlist(settings.realtime_watchlist)
    now = datetime.now(UTC)
    ticks = await get_latest_ticks(redis, watchlist)

    finalized: list[Candle] = []
    for symbol, tick in ticks.items():
        # get_latest_ticks returns the last KNOWN value, which the
        # collector keeps cached for up to an hour after the feed dies --
        # folding a stale cached price into the current bucket would
        # fabricate a flat candle for a symbol that isn't actually trading
        # on the feed right now.
        if (now - tick.event_timestamp).total_seconds() > settings.realtime_freshness_stale_seconds:
            continue

        key = f"{CANDLE_KEY_PREFIX}{symbol}"
        raw = await redis.get(key)
        state = BucketState.from_json(raw) if raw else None
        bucket = bucket_start(tick.event_timestamp)

        if state is not None and state.bucket_start != bucket:
            finalized.append(state.to_candle(symbol))
            state = None

        if state is None:
            state = BucketState.start(bucket, tick)
        elif tick.event_timestamp != state.last_tick_at:
            # Skip when the cached tick's timestamp hasn't moved since the
            # last poll -- the feed hasn't actually produced a new price,
            # re-counting it would inflate tick_count for no reason.
            state.extend(tick)

        await redis.set(key, state.to_json(), ex=settings.realtime_candle_state_ttl_seconds)

    if finalized:
        await upsert_candles(session_factory, CryptoHistory, finalized)
        finalized_symbols = sorted({c.symbol for c in finalized})
        for symbol in finalized_symbols:
            await fill_missing_indicators(
                session_factory, CryptoHistory, symbol, Timeframe.FIVE_MINUTE
            )
            await _roll_up_fifteen_minute(session_factory, symbol)
        logger.info(
            "Realtime candle aggregation: %d 5m candle(s) finalized (%s)",
            len(finalized),
            ", ".join(finalized_symbols),
        )

    return [c.symbol for c in finalized]


async def _roll_up_fifteen_minute(
    session_factory: async_sessionmaker[AsyncSession], symbol: str
) -> None:
    """Derives 15m candles by resampling the stored 5m series. Only ever
    resamples 5m bars from *fully elapsed* 15-minute windows -- the
    in-progress window's bars aren't all in yet, and upsert_candles' ON
    CONFLICT DO NOTHING would otherwise permanently freeze a premature,
    too-narrow 15m candle in place the moment one gets written, since a
    later re-resample including the rest of that window's bars would then
    be silently skipped as "already exists"."""
    five_min_rows = await get_series(session_factory, CryptoHistory, symbol, Timeframe.FIVE_MINUTE)
    if not five_min_rows:
        return

    current_15m_bucket_start = _floor_to_minutes(datetime.now(UTC), 15)
    eligible_rows = [r for r in five_min_rows if r.timestamp < current_15m_bucket_start]
    if not eligible_rows:
        return

    five_min_candles = [
        Candle(
            symbol=symbol,
            timeframe=Timeframe.FIVE_MINUTE,
            timestamp=row.timestamp,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume) if row.volume is not None else None,
            source=row.source,
        )
        for row in eligible_rows
    ]
    fifteen_min_candles = resample_candles(five_min_candles, Timeframe.FIFTEEN_MINUTE)
    await upsert_candles(session_factory, CryptoHistory, fifteen_min_candles)
    await fill_missing_indicators(session_factory, CryptoHistory, symbol, Timeframe.FIFTEEN_MINUTE)
