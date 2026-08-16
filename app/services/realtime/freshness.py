"""Multi-tier data-freshness classification. A sibling to
app.services.watchdog.provider_health's binary healthy/stale check (left
untouched, still used for its existing Watchdog contract) -- this is the
finer-grained live/recent/delayed/stale/offline scale the realtime price
path, /api/market, and the source-status panel all need, per the user's
explicit instruction not to hardcode thresholds when a configuration
system already exists (see app.config.settings's realtime_freshness_*
fields).
"""

from datetime import UTC, datetime

from app.config import Settings

FreshnessState = str  # "live" | "recent" | "delayed" | "stale" | "offline"


def age_seconds(reference: datetime, *, now: datetime | None = None) -> float:
    now = now or datetime.now(UTC)
    return (now - reference).total_seconds()


def classify_freshness(
    age_seconds: float,
    *,
    live_seconds: float,
    recent_seconds: float,
    delayed_seconds: float,
    stale_seconds: float,
) -> FreshnessState:
    age_seconds = max(age_seconds, 0.0)
    if age_seconds < live_seconds:
        return "live"
    if age_seconds < recent_seconds:
        return "recent"
    if age_seconds < delayed_seconds:
        return "delayed"
    if age_seconds < stale_seconds:
        return "stale"
    return "offline"


def classify_freshness_from_settings(age_seconds: float, settings: Settings) -> FreshnessState:
    return classify_freshness(
        age_seconds,
        live_seconds=settings.realtime_freshness_live_seconds,
        recent_seconds=settings.realtime_freshness_recent_seconds,
        delayed_seconds=settings.realtime_freshness_delayed_seconds,
        stale_seconds=settings.realtime_freshness_stale_seconds,
    )
