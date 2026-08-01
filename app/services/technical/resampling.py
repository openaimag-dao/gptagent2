"""Derives weekly candles from this project's own stored daily OHLCV --
honest secondary computation, not a new data source: every input value
already came from a provider this project already trusts (see
app.services.history.registry). This is how the "1W" timeframe in the
multi-timeframe analysis is covered without a live weekly feed.
"""

from dataclasses import dataclass
from datetime import datetime


@dataclass
class ResampledCandle:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None


def resample_to_weekly(rows: list) -> list[ResampledCandle]:
    """`rows` are ascending daily OHLCV rows with .timestamp/.open/.high/
    .low/.close/.volume attributes. Groups by ISO week (Mon-Sun)."""
    buckets: dict[tuple[int, int], list] = {}
    for row in rows:
        key = row.timestamp.isocalendar()[:2]
        buckets.setdefault(key, []).append(row)

    weekly: list[ResampledCandle] = []
    for key in sorted(buckets):
        week_rows = buckets[key]
        volumes = [float(r.volume) for r in week_rows if r.volume is not None]
        weekly.append(
            ResampledCandle(
                timestamp=week_rows[-1].timestamp,
                open=float(week_rows[0].open),
                high=max(float(r.high) for r in week_rows),
                low=min(float(r.low) for r in week_rows),
                close=float(week_rows[-1].close),
                volume=sum(volumes) if volumes else None,
            )
        )
    return weekly
