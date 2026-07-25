"""Pure gap/duplicate detection over a symbol/timeframe's stored timestamps -- no I/O."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from app.services.history.schemas import Timeframe

_STEP_BY_TIMEFRAME: dict[Timeframe, timedelta] = {
    Timeframe.DAILY: timedelta(days=1),
    Timeframe.FOUR_HOUR: timedelta(hours=4),
    Timeframe.ONE_HOUR: timedelta(hours=1),
}

# Equity/macro markets close on weekends and holidays, so a "gap" there is
# only real once it's meaningfully larger than the expected step -- otherwise
# every single weekend would be flagged as missing data. Crypto trades 24/7,
# so its tolerance stays tight.
_GAP_TOLERANCE_MULTIPLIER: dict[str, float] = {"crypto": 1.5, "equity": 4.0}


@dataclass(frozen=True)
class Gap:
    after: datetime
    before: datetime


@dataclass
class ValidationReport:
    symbol: str
    timeframe: Timeframe
    duplicate_timestamps: list[datetime] = field(default_factory=list)
    gaps: list[Gap] = field(default_factory=list)


def find_duplicate_timestamps(timestamps: list[datetime]) -> list[datetime]:
    seen: set[datetime] = set()
    duplicates: list[datetime] = []
    for ts in timestamps:
        if ts in seen:
            duplicates.append(ts)
        seen.add(ts)
    return duplicates


def find_gaps(
    timestamps: list[datetime], timeframe: Timeframe, market: str = "crypto"
) -> list[Gap]:
    """`timestamps` must already be sorted ascending and de-duplicated."""
    if len(timestamps) < 2:
        return []

    step = _STEP_BY_TIMEFRAME[timeframe]
    tolerance = _GAP_TOLERANCE_MULTIPLIER.get(market, _GAP_TOLERANCE_MULTIPLIER["crypto"])
    threshold = step * tolerance

    return [
        Gap(after=prev, before=curr)
        for prev, curr in zip(timestamps, timestamps[1:])
        if curr - prev > threshold
    ]


def validate_series(
    symbol: str, timeframe: Timeframe, timestamps: list[datetime], market: str = "crypto"
) -> ValidationReport:
    duplicates = find_duplicate_timestamps(timestamps)
    gaps = find_gaps(sorted(set(timestamps)), timeframe, market)
    return ValidationReport(
        symbol=symbol, timeframe=timeframe, duplicate_timestamps=duplicates, gaps=gaps
    )
