"""Pure detection functions for the v5.5 Market Scanner. Mirrors the
discipline established by app.services.shocks.detectors (v5.1) and
app.services.watchdog.detectors (v5.4): every function here takes
already-computed readings and returns a plain dict/str/None -- no I/O, no
Telegram, fully unit-testable in isolation from "where the data comes
from". Escalation/quality-gating machinery (SEVERITY_ORDER, gate_severity,
should_notify, decide_alert_action, score_alert_quality,
regime/consensus/committee_alignment_score, compute_realized_volatility,
compute_window_changes, detect_multi_asset_shock) is REUSED directly from
app.services.shocks.detectors in engine.py, not reimplemented here.
"""

# ---- Price event detection ----

DEFAULT_PRICE_LADDER: tuple[float, float, float, float] = (3.0, 5.0, 8.0, 10.0)

# Per-asset threshold overrides -- the mission's "Configurable per asset".
# Empty by default (every symbol uses DEFAULT_PRICE_LADDER); populate to
# give specific symbols a tighter/looser ladder.
PRICE_LADDER_OVERRIDES: dict[str, tuple[float, float, float, float]] = {}

# DEFAULT_PRICE_LADDER's absolute percentages were sized around roughly
# BTC's typical realized daily volatility -- a symbol trading at a
# materially different realized volatility gets its ladder scaled
# proportionally instead of being compared against the same flat
# thresholds as BTC (a 3% move is routine for a name that swings 15%/day,
# and unusually large for one that swings 1%/day).
_REFERENCE_VOLATILITY_PCT = 2.0
_DEFAULT_VOL_MULTIPLIER_MIN = 0.5
_DEFAULT_VOL_MULTIPLIER_MAX = 2.5

_SEVERITY_LABELS: tuple[str, ...] = ("info", "important", "high", "critical")


def price_ladder_for(
    symbol: str,
    realized_volatility_pct: float | None = None,
    reference_volatility_pct: float = _REFERENCE_VOLATILITY_PCT,
    min_multiplier: float = _DEFAULT_VOL_MULTIPLIER_MIN,
    max_multiplier: float = _DEFAULT_VOL_MULTIPLIER_MAX,
) -> tuple[float, float, float, float]:
    """`realized_volatility_pct` (this symbol's own recent realized
    volatility, e.g. from compute_realized_volatility) is optional --
    omitted (the default), this returns the flat unscaled ladder exactly
    as before. Given, the ladder is scaled by
    realized_volatility_pct/reference_volatility_pct, clamped to
    [min_multiplier, max_multiplier] so one extremely quiet or extremely
    volatile reading can't collapse or blow out the thresholds entirely.
    """
    base = PRICE_LADDER_OVERRIDES.get(symbol.upper(), DEFAULT_PRICE_LADDER)
    if realized_volatility_pct is None or realized_volatility_pct <= 0:
        return base
    ratio = realized_volatility_pct / reference_volatility_pct
    multiplier = max(min_multiplier, min(max_multiplier, ratio))
    return tuple(round(threshold * multiplier, 4) for threshold in base)


def classify_price_event(
    symbol: str,
    pct_change: float | None,
    realized_volatility_pct: float | None = None,
    min_multiplier: float = _DEFAULT_VOL_MULTIPLIER_MIN,
    max_multiplier: float = _DEFAULT_VOL_MULTIPLIER_MAX,
) -> dict | None:
    """Highest tier whose threshold |pct_change| clears, or None below
    "info"."""
    if pct_change is None:
        return None
    ladder = price_ladder_for(
        symbol,
        realized_volatility_pct,
        min_multiplier=min_multiplier,
        max_multiplier=max_multiplier,
    )
    magnitude = abs(pct_change)
    tier = None
    for label, threshold in zip(_SEVERITY_LABELS, ladder, strict=True):
        if magnitude >= threshold:
            tier = label
    if tier is None:
        return None
    return {
        "symbol": symbol,
        "direction": "up" if pct_change > 0 else "down",
        "pct_change": pct_change,
        "tier": tier,
    }


# ---- Volume detection ----

_VOLUME_MULTIPLE_LADDER: tuple[tuple[float, str], ...] = (
    (10.0, "Volume x10"),
    (5.0, "Volume x5"),
    (3.0, "Volume x3"),
    (2.0, "Volume x2"),
)


def detect_volume_multiple(
    current_volume: float | None, historical_avg_volume: float | None
) -> dict | None:
    """Compares current volume against a trailing historical average --
    None if either side is missing/zero (never divide by zero, never
    fabricate a multiple)."""
    if not current_volume or not historical_avg_volume:
        return None
    multiple = current_volume / historical_avg_volume
    for threshold, label in _VOLUME_MULTIPLE_LADDER:
        if multiple >= threshold:
            return {"label": label, "multiple": round(multiple, 2)}
    return None


# ---- Volatility detection ----

_FLASH_MOVE_THRESHOLD_PCT = 8.0  # within a single short window (e.g. 15m)
_ABNORMAL_VOL_MULTIPLE = 2.5
_VOL_EXPANSION_MULTIPLE = 1.8
_LOW_VOL_COMPRESSION_MULTIPLE = 0.4


def detect_flash_move(short_window_pct_change: float | None) -> str | None:
    if short_window_pct_change is None:
        return None
    if short_window_pct_change <= -_FLASH_MOVE_THRESHOLD_PCT:
        return "Flash Crash"
    if short_window_pct_change >= _FLASH_MOVE_THRESHOLD_PCT:
        return "Flash Rally"
    return None


def detect_volatility_regime(
    current_realized_vol: float | None, baseline_realized_vol: float | None
) -> str | None:
    """Compares this cycle's realized volatility (compute_realized_volatility
    over a recent price window) against a longer-run baseline -- Abnormal
    Volatility on a sharp multiple-of-baseline spike, Volatility Expansion
    on a milder but still elevated spike, Low Volatility Compression when
    volatility has collapsed well below baseline (often a pre-breakout
    setup)."""
    if current_realized_vol is None or not baseline_realized_vol:
        return None
    ratio = current_realized_vol / baseline_realized_vol
    if ratio >= _ABNORMAL_VOL_MULTIPLE:
        return "Abnormal Volatility"
    if ratio >= _VOL_EXPANSION_MULTIPLE:
        return "Volatility Expansion"
    if ratio <= _LOW_VOL_COMPRESSION_MULTIPLE:
        return "Low Volatility Compression"
    return None


# ---- Breakout detection ----


def detect_new_high_low(
    price: float, period_high: float | None, period_low: float | None
) -> str | None:
    if period_high is not None and price > period_high:
        return "New Daily High"
    if period_low is not None and price < period_low:
        return "New Daily Low"
    return None


def detect_range_breakout(
    price: float, period_high: float | None, period_low: float | None, label: str
) -> str | None:
    """Generic version of detect_new_high_low for a wider period (weekly/
    monthly) -- `label` names which one fired (e.g. "Weekly Breakout")."""
    if period_high is not None and price > period_high:
        return f"{label} (Up)"
    if period_low is not None and price < period_low:
        return f"{label} (Down)"
    return None


def detect_support_resistance_break(
    price: float, support: float | None, resistance: float | None
) -> str | None:
    if resistance is not None and price > resistance:
        return "Resistance Break"
    if support is not None and price < support:
        return "Support Break"
    return None


_TREND_CHANGE_THRESHOLD = 10.0


def detect_trend_change(
    prev_trend_strength: float | None, curr_trend_strength: float | None
) -> str | None:
    """Only meaningful for the subset of scanned symbols with a Technical
    Analysis Engine reading (v5.3) -- most of the ~500-symbol scanner
    universe has no trend-strength score to compare, so this honestly
    returns None for them rather than guessing."""
    if prev_trend_strength is None or curr_trend_strength is None:
        return None
    delta = curr_trend_strength - prev_trend_strength
    if delta >= _TREND_CHANGE_THRESHOLD:
        return "Trend Acceleration"
    if delta <= -_TREND_CHANGE_THRESHOLD:
        return "Trend Weakening"
    return None


# ---- Sector / ecosystem events ----

_SECTOR_ECOSYSTEM_THRESHOLD_PCT = 5.0
# >= 2, not 1: the mission's own worked example needs multiple independent
# movers ("AI sector up, Semiconductors up, SOL up"). At 1, a sector with
# only a single tracked member would "corroborate" itself, firing a
# redundant ecosystem alert alongside that coin's own individual price
# event for every single-coin sector -- caught by
# tests/test_scanner_engine.py::test_run_cycle_detects_standalone_price_event.
_SECTOR_ECOSYSTEM_MIN_STRONG_MOVERS = 2

_ECOSYSTEM_EVENT_NAMES: dict[str, str] = {
    "AI": "AI ECOSYSTEM STRENGTHENING",
    "Layer 1": "LAYER 1 ECOSYSTEM STRENGTHENING",
    "Layer 2": "LAYER 2 ECOSYSTEM STRENGTHENING",
    "RWA": "RWA ECOSYSTEM STRENGTHENING",
    "Gaming": "GAMING ECOSYSTEM STRENGTHENING",
    "Meme": "MEME ECOSYSTEM STRENGTHENING",
    "DeFi": "DEFI ECOSYSTEM STRENGTHENING",
    "DePIN": "DEPIN ECOSYSTEM STRENGTHENING",
    "Infrastructure": "INFRASTRUCTURE ECOSYSTEM STRENGTHENING",
    "Stablecoins": "STABLECOIN ECOSYSTEM SHIFT",
}


def detect_sector_ecosystem_event(
    sector: str,
    avg_change_pct_24h: float | None,
    member_price_events: list[dict | None],
    threshold_pct: float = _SECTOR_ECOSYSTEM_THRESHOLD_PCT,
    min_strong_movers: int = _SECTOR_ECOSYSTEM_MIN_STRONG_MOVERS,
) -> dict | None:
    """One "<SECTOR> ECOSYSTEM STRENGTHENING/WEAKENING" event when a
    sector's average 24h change clears `threshold_pct` AND at least
    `min_strong_movers` of ITS OWN coins (`member_price_events` -- one
    classify_price_event() result or None per coin in that sector)
    independently cleared a price-event tier in the same direction.
    Mirrors the mission's worked example ("AI sector up, Semiconductors
    up, SOL up -> AI ECOSYSTEM STRENGTHENING") -- a different combination
    (sector average + individual corroboration) from
    detect_multi_asset_shock's synchronized-move-across-a-fixed-list
    algorithm, so not reusing that function here would be reimplementing
    it; this genuinely is new logic."""
    if avg_change_pct_24h is None or abs(avg_change_pct_24h) < threshold_pct:
        return None
    direction = "up" if avg_change_pct_24h > 0 else "down"
    strong_movers = [
        d for d in member_price_events if d is not None and d["direction"] == direction
    ]
    if len(strong_movers) < min_strong_movers:
        return None
    title = _ECOSYSTEM_EVENT_NAMES.get(sector, f"{sector.upper()} ECOSYSTEM SHIFT")
    if direction == "down":
        title = title.replace("STRENGTHENING", "WEAKENING")
    return {
        "category": "sector_ecosystem",
        "sector": sector,
        "title": title,
        "direction": direction,
        "avg_change_pct_24h": avg_change_pct_24h,
        "corroborating_symbols": [d["symbol"] for d in strong_movers],
    }
