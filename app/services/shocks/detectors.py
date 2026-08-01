"""Pure functions for the Autonomous Critical Alert System (v5.1) -- a
SECOND, independent alert layer alongside (not replacing) the Smart Alert
Engine (app/services/alerts/engine.py) and Configurable Alerts
(app/services/alerts/rules.py). No user configures anything here: severity
is decided entirely from price action plus a composite quality read built
from signals this platform already computes.

Time windows: prices are collected every `market_data_interval_minutes`
(5 minutes in production -- app/config/settings.py) into a real historical
time series (a new SnapshotBatch + AssetPrice rows every cycle, never
overwritten). 5 minutes is therefore the finest window this system can
honestly support -- a 1-minute window would need a dedicated per-minute
poller this project doesn't have, and standing one up would multiply
provider API calls roughly 5x for no other engine that would use it.
Omitted rather than faked.
"""

import statistics
from datetime import datetime, timedelta
from typing import Any

from app.services.common.scoring import clamp, weighted_average

# Regime/verdict/decision labels bucketed into a directional bias, used to
# score whether other engines' current reads corroborate a shock's direction
# rather than contradicting it.
_BEARISH_REGIME_MARKERS = ("bear", "risk_off", "distribution", "capitulation")
_BULLISH_REGIME_MARKERS = ("bull", "risk_on", "altseason", "recovery")

WINDOWS_MINUTES: dict[str, int] = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "24h": 1440,
}

SEVERITY_ORDER: tuple[str, ...] = ("info", "important", "high", "critical")

# Four ascending absolute-move thresholds per symbol: info/important/high/critical.
# All in code, all easy to retune here -- nothing is user-configurable.
# FEAR_GREED is a 0-100 index, not a %-priced asset, so its ladder is index points.
THRESHOLDS: dict[str, tuple[float, float, float, float]] = {
    "BTC": (3.0, 5.0, 8.0, 10.0),
    "ETH": (3.0, 5.0, 8.0, 12.0),
    "SOL": (5.0, 8.0, 10.0, 15.0),
    "NASDAQ": (2.0, 3.0, 4.0, 6.0),
    "SPX": (1.5, 2.0, 3.0, 4.5),
    "DJI": (1.5, 2.0, 3.0, 4.5),
    "DXY": (0.5, 1.0, 1.5, 2.0),
    "GOLD": (1.0, 2.0, 3.0, 4.0),
    "OIL": (2.0, 4.0, 6.0, 9.0),
    "VIX": (10.0, 15.0, 25.0, 40.0),
    "US10Y": (2.0, 4.0, 6.0, 9.0),
    "FEAR_GREED": (10.0, 15.0, 25.0, 35.0),
}

MONITORED_SYMBOLS: tuple[str, ...] = tuple(THRESHOLDS.keys())

_MULTI_ASSET_SYMBOLS: tuple[str, ...] = ("BTC", "ETH", "SOL", "NASDAQ", "SPX", "DJI")
_MULTI_ASSET_MIN_COUNT = 3
_MULTI_ASSET_MIN_TIER = "important"

NOTIFY_TIERS: tuple[str, ...] = ("high", "critical")

_QUALITY_WEIGHTS: dict[str, float] = {
    "volume": 10.0,
    "volatility": 15.0,
    "regime_alignment": 15.0,
    "trend_strength": 10.0,
    "consensus_alignment": 15.0,
    "committee_alignment": 15.0,
    "historical_similarity": 5.0,
    "risk_score": 10.0,
    "confidence_score": 5.0,
}


def classify_tier(symbol: str, pct_change: float) -> str | None:
    """Highest tier whose threshold |pct_change| clears, or None below `info`."""
    ladder = THRESHOLDS.get(symbol)
    if ladder is None:
        return None
    magnitude = abs(pct_change)
    tier = None
    for label, threshold in zip(SEVERITY_ORDER, ladder, strict=True):
        if magnitude >= threshold:
            tier = label
    return tier


def compute_window_changes(
    history: list[Any], now: datetime, windows: dict[str, int] = WINDOWS_MINUTES
) -> dict[str, float | None]:
    """Pure: given ascending-by-`recorded_at` rows (each needs `.price` and
    `.recorded_at`, e.g. AssetPrice) and the current time, returns the %
    change from the row closest to `now - window` to the latest row, for
    every window. Nearest-neighbor rather than exact-timestamp match, since
    rows land every `market_data_interval_minutes` (~5 min in production),
    not on the window boundary itself. Shared by CriticalAlertEngine
    (app/services/shocks/engine.py) and the v5.4 Watchdog hub's Crypto/Macro
    Overview so both read the exact same windowing logic rather than each
    reimplementing it."""
    if not history:
        return {w: None for w in windows}
    prices = [float(row.price) for row in history]
    latest_price = prices[-1]
    changes: dict[str, float | None] = {}
    for window, minutes in windows.items():
        target = now - timedelta(minutes=minutes)
        earlier_row = min(history, key=lambda r: abs((r.recorded_at - target).total_seconds()))
        earlier_price = float(earlier_row.price)
        changes[window] = (
            (latest_price - earlier_price) / earlier_price * 100 if earlier_price else None
        )
    return changes


def best_window_detection(symbol: str, changes_by_window: dict[str, float | None]) -> dict | None:
    """Picks the single (window, tier) worth alerting on out of every window
    checked for this symbol: highest tier first, shortest window (more
    urgent) as the tiebreaker. None if nothing clears `info` in any window."""
    candidates = []
    for window, pct in changes_by_window.items():
        if pct is None:
            continue
        tier = classify_tier(symbol, pct)
        if tier is None:
            continue
        minutes = WINDOWS_MINUTES.get(window, 0)
        candidates.append((SEVERITY_ORDER.index(tier), -minutes, window, pct, tier))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    _, _, window, pct, tier = candidates[0]
    return {"symbol": symbol, "window": window, "pct_change": pct, "tier": tier}


def detect_multi_asset_shock(
    per_symbol_detections: dict[str, dict | None],
    symbols: tuple[str, ...] = _MULTI_ASSET_SYMBOLS,
    min_count: int = _MULTI_ASSET_MIN_COUNT,
    min_tier: str = _MULTI_ASSET_MIN_TIER,
    category: str = "multi_asset_shock",
) -> dict | None:
    """One combined Market Shock instead of several individual alerts when
    >= `min_count` of `symbols` move the same direction at >= `min_tier`
    simultaneously. Defaults to v5.1's original cross-asset risk basket
    (BTC/ETH/SOL/NASDAQ/SPX/DJI); the v5.5 Market Scanner reuses this same
    function with its own crypto-only symbol list and a "crypto_market_shock"
    category instead of reimplementing the same synchronized-move logic."""
    min_rank = SEVERITY_ORDER.index(min_tier)
    down_moves = []
    up_moves = []
    for symbol in symbols:
        detection = per_symbol_detections.get(symbol)
        if detection is None or SEVERITY_ORDER.index(detection["tier"]) < min_rank:
            continue
        (down_moves if detection["pct_change"] < 0 else up_moves).append(detection)

    moves = down_moves if len(down_moves) >= len(up_moves) else up_moves
    if len(moves) < min_count:
        return None

    direction = "down" if moves is down_moves else "up"
    max_tier = max(moves, key=lambda d: SEVERITY_ORDER.index(d["tier"]))["tier"]
    # A synchronized move across N assets is inherently more significant than
    # any single one of them -- escalate one tier beyond the worst individual
    # reading, capped at "critical".
    escalated_rank = min(SEVERITY_ORDER.index(max_tier) + 1, len(SEVERITY_ORDER) - 1)
    return {
        "category": category,
        "direction": direction,
        "tier": SEVERITY_ORDER[escalated_rank],
        "moves": moves,
    }


def compute_realized_volatility(prices: list[float]) -> float | None:
    """Stdev of consecutive-snapshot pct returns across a window, as a %
    figure -- a plain statistical read of the price series already fetched
    for that window, not a new data source."""
    if len(prices) < 3:
        return None
    returns = []
    for prev, curr in zip(prices[:-1], prices[1:], strict=True):
        if prev:
            returns.append((curr - prev) / prev * 100)
    if len(returns) < 2:
        return None
    return statistics.stdev(returns)


def regime_direction_bucket(label: str | None) -> str:
    """ "bullish"/"bearish"/"neutral" bucket for a regime (or similar) label
    string -- shared by this module's regime_alignment_score() and the
    v5.4 Watchdog hub's Market Overview "Trend" field, so both read the
    exact same bull/bear market-regime word lists rather than each keeping
    its own copy."""
    if label is None:
        return "neutral"
    value = label.lower()
    if any(marker in value for marker in _BEARISH_REGIME_MARKERS):
        return "bearish"
    if any(marker in value for marker in _BULLISH_REGIME_MARKERS):
        return "bullish"
    return "neutral"


def regime_alignment_score(regime_value: str | None, move_direction: str) -> float | None:
    """0-100: does the current market regime corroborate this shock's
    direction? Neutral regimes score a flat midpoint rather than favoring
    either direction."""
    if regime_value is None:
        return None
    bucket = regime_direction_bucket(regime_value)
    if bucket == "neutral":
        return 50.0
    return 100.0 if bucket == move_direction else 0.0


def consensus_alignment_score(
    bullish_pct: float | None,
    bearish_pct: float | None,
    agreement_score: float | None,
    move_direction: str,
) -> float | None:
    """0-100: does the 5-agent consensus vote corroborate this shock's
    direction? Scaled by how strongly the agents agree with each other."""
    if bullish_pct is None or bearish_pct is None or agreement_score is None:
        return None
    dominant = "bullish" if bullish_pct >= bearish_pct else "bearish"
    return agreement_score if dominant == move_direction else (100.0 - agreement_score)


def committee_alignment_score(
    majority_decision: str | None, majority_pct: float | None, move_direction: str
) -> float | None:
    """0-100: does the AI Investment Committee's majority decision
    corroborate this shock's direction? BUY/SELL map to bullish/bearish;
    HOLD is neutral."""
    if majority_decision is None or majority_pct is None:
        return None
    bucket = {"BUY": "bullish", "SELL": "bearish"}.get(majority_decision, "neutral")
    if bucket == "neutral":
        return 50.0
    return majority_pct if bucket == move_direction else (100.0 - majority_pct)


def historical_similarity_score(
    forward_returns_1d: list[float | None], move_direction: str
) -> float | None:
    """0-100: of the K most similar historical episodes, what share
    continued in this shock's direction over the next period?"""
    signed = [r for r in forward_returns_1d if r is not None]
    if not signed:
        return None
    matching = sum(1 for r in signed if (r > 0) == (move_direction == "bullish"))
    return round(100.0 * matching / len(signed), 1)


def volume_change_score(volume_pct_change: float | None) -> float | None:
    """0-100: a volume spike alongside the price move raises confidence
    it's real rather than a thin-liquidity wick."""
    if volume_pct_change is None:
        return None
    return clamp(50.0 + volume_pct_change)


def volatility_score(realized_volatility_pct: float | None, scale: float = 10.0) -> float | None:
    """0-100: elevated realized volatility during the window corroborates
    an abnormal-move read. `scale` is the volatility level (in %) that
    saturates the score at 100 -- a heuristic calibration, not a claim of
    statistical precision."""
    if realized_volatility_pct is None:
        return None
    return clamp(realized_volatility_pct / scale * 100.0)


def score_alert_quality(components: dict[str, float | None]) -> float | None:
    """Composite 0-100 "is this shock corroborated" score built only from
    signals this platform already computes -- never a new measurement.
    Missing components (engine not configured, no data yet) are excluded
    from the average rather than defaulted, matching this project's
    honesty precedent everywhere else."""
    return weighted_average(components, _QUALITY_WEIGHTS)


def gate_severity(raw_tier: str, quality_score: float | None, min_quality: float = 40.0) -> str:
    """Quality can only soften a tier by one step, never upgrade it or
    suppress it outright -- an unmistakably large move (e.g. BTC -10%)
    still reaches the user even on a weak quality read; only a borderline
    high/critical call gets downgraded when nothing else corroborates it."""
    if quality_score is not None and quality_score < min_quality:
        rank = max(SEVERITY_ORDER.index(raw_tier) - 1, 0)
        return SEVERITY_ORDER[rank]
    return raw_tier


def should_notify(tier: str) -> bool:
    return tier in NOTIFY_TIERS


def decide_alert_action(
    existing_active: bool,
    existing_tier: str | None,
    new_tier: str,
    now: datetime,
    last_updated_at: datetime | None,
    resolve_after_minutes: int = 120,
) -> str:
    """Returns "new" | "escalate" | "suppress" | "resolve_then_new".

    An active episode whose last update is older than `resolve_after_minutes`
    is treated as finished -- the next detection starts a fresh message
    rather than reopening a stale one. Escalation only fires when the new
    tier is strictly worse than the stored one; anything else on an active
    episode is suppressed so identical/declining readings never spam."""
    if existing_active and last_updated_at is not None:
        if now - last_updated_at > timedelta(minutes=resolve_after_minutes):
            return "resolve_then_new"
    if not existing_active:
        return "new"
    if existing_tier is not None and SEVERITY_ORDER.index(new_tier) > SEVERITY_ORDER.index(
        existing_tier
    ):
        return "escalate"
    return "suppress"
