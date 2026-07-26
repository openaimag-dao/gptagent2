"""Pure nearest-timestamp matching -- no I/O. Used to line up an event date
(e.g. a CPI release, midnight UTC) with the nearest actual stored trading
bar, since markets aren't necessarily open exactly then."""

from datetime import datetime


def nearest_bar_index(
    timestamps: list[datetime], target: datetime, tolerance_days: float = 3.0
) -> int | None:
    """Index of the timestamp closest to `target`, or None if nothing is
    within `tolerance_days` (e.g. a weekend FOMC-adjacent date with no
    trading bar nearby at all)."""
    if not timestamps:
        return None
    best_idx = 0
    best_delta = abs((timestamps[0] - target).total_seconds())
    for i in range(1, len(timestamps)):
        delta = abs((timestamps[i] - target).total_seconds())
        if delta < best_delta:
            best_delta = delta
            best_idx = i
    if best_delta > tolerance_days * 86400:
        return None
    return best_idx
