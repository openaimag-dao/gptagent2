"""Pure functions for the v5.4 Watchdog hub: significant-change detection
between two consecutive WatchdogSnapshot cycles ("Automatic Detection"),
plus small classification helpers used across the Current Market
Status/Market Overview sections. Every detector here takes already-computed
"previous"/"current" numbers (the same discipline as
app/services/alerts/detectors.py) -- nothing here fetches data itself, so
each function is trivially unit-testable and "what counts as a change" stays
fully separate from "where the data comes from".
"""

_TREND_STRENGTH_THRESHOLD = 10
_CONFIDENCE_THRESHOLD = 15
_RISK_THRESHOLD = 15
_LIQUIDITY_THRESHOLD = 15
_VOLATILITY_SPIKE_THRESHOLD = 15


def classify_market_health(global_score: int | None) -> str:
    """A single at-a-glance label for "Current Market Status" -- derived
    entirely from the Global Market Score another engine already computed,
    never a new measurement."""
    if global_score is None:
        return "Unknown"
    if global_score >= 70:
        return "Healthy"
    if global_score >= 40:
        return "Watch"
    return "Stressed"


def classify_bias(bullish_score: float | None, bearish_score: float | None) -> str | None:
    """ "Bullish"/"Bearish"/"Neutral" from an already-computed technical
    bullish/bearish score pair (TechnicalAnalysisSnapshot) -- the same
    kind of small bucketing used for "AI Bias" in the Crypto/Macro
    Overview tables."""
    if bullish_score is None or bearish_score is None:
        return None
    delta = bullish_score - bearish_score
    if delta >= 10:
        return "Bullish"
    if delta <= -10:
        return "Bearish"
    return "Neutral"


def freshness_status(last_updated, max_age_seconds: float, now) -> str:
    """ "ok"/"stale"/"unavailable" for a Current Market Status sub-engine
    (Brain/Replay) -- "unavailable" when it has never produced a reading,
    "stale" when its last reading is older than `max_age_seconds`, "ok"
    otherwise. A generic, timestamp-only freshness check, not specific to
    any one engine."""
    if last_updated is None:
        return "unavailable"
    age = (now - last_updated).total_seconds()
    return "ok" if age <= max_age_seconds else "stale"


def _magnitude_change_event(
    prev: float | None,
    curr: float | None,
    threshold: float,
    increase_type: str,
    decrease_type: str,
    label: str,
) -> dict | None:
    if prev is None or curr is None:
        return None
    delta = curr - prev
    if delta >= threshold:
        return {
            "event_type": increase_type,
            "message": f"{label} rose from {prev} to {curr}.",
            "data": {"prev": prev, "curr": curr, "delta": round(delta, 2)},
        }
    if delta <= -threshold:
        return {
            "event_type": decrease_type,
            "message": f"{label} fell from {prev} to {curr}.",
            "data": {"prev": prev, "curr": curr, "delta": round(delta, 2)},
        }
    return None


def detect_trend_strength_change(
    prev: float | None, curr: float | None, threshold: float = _TREND_STRENGTH_THRESHOLD
) -> dict | None:
    return _magnitude_change_event(
        prev, curr, threshold, "TrendStrengthIncreased", "TrendStrengthDecreased", "Trend strength"
    )


def detect_confidence_change(
    prev: float | None, curr: float | None, threshold: float = _CONFIDENCE_THRESHOLD
) -> dict | None:
    return _magnitude_change_event(
        prev, curr, threshold, "ConfidenceIncreased", "ConfidenceDropped", "Confidence"
    )


def detect_risk_change(
    prev: float | None, curr: float | None, threshold: float = _RISK_THRESHOLD
) -> dict | None:
    # Note the label order: a RISING risk_score is a worsening condition, so
    # it maps to "RiskIncreased" (bad) not the generic increase/decrease
    # wording of the other detectors -- kept explicit here for clarity.
    return _magnitude_change_event(
        prev, curr, threshold, "RiskIncreased", "RiskReduced", "Risk score"
    )


def detect_liquidity_shift(
    prev: float | None, curr: float | None, threshold: float = _LIQUIDITY_THRESHOLD
) -> dict | None:
    if prev is None or curr is None:
        return None
    delta = curr - prev
    if abs(delta) < threshold:
        return None
    direction = "up" if delta > 0 else "down"
    return {
        "event_type": "LiquidityShift",
        "message": f"Liquidity score shifted {direction} from {prev} to {curr}.",
        "data": {"prev": prev, "curr": curr, "delta": round(delta, 2), "direction": direction},
    }


def detect_volatility_spike(
    prev: float | None, curr: float | None, threshold: float = _VOLATILITY_SPIKE_THRESHOLD
) -> dict | None:
    """Only fires on a spike (increase) -- a calming volatility read isn't
    itself a "spike" event worth surfacing."""
    if prev is None or curr is None:
        return None
    delta = curr - prev
    if delta < threshold:
        return None
    return {
        "event_type": "VolatilitySpike",
        "message": f"Volatility jumped from {prev} to {curr}.",
        "data": {"prev": prev, "curr": curr, "delta": round(delta, 2)},
    }


def detect_committee_change(prev_decision: str | None, curr_decision: str | None) -> dict | None:
    if prev_decision is None or curr_decision is None or prev_decision == curr_decision:
        return None
    return {
        "event_type": "CommitteeChanged",
        "message": f"AI Investment Committee decision changed: {prev_decision} -> {curr_decision}.",
        "data": {"prev": prev_decision, "curr": curr_decision},
    }


def detect_regime_changed_event(prev_regime: str | None, curr_regime: str | None) -> dict | None:
    if prev_regime is None or curr_regime is None or prev_regime == curr_regime:
        return None
    return {
        "event_type": "MarketRegimeChanged",
        "message": f"Market regime changed: {prev_regime} -> {curr_regime}.",
        "data": {"prev": prev_regime, "curr": curr_regime},
    }


# Telegram only fires for a subset of these event types -- "Never spam" --
# matching the mission's explicit list (regime change, significant
# confidence change, sharp risk jump, committee direction change; market
# shock is already covered by the v5.1 Critical Alert System, not
# duplicated here).
TELEGRAM_ELIGIBLE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "MarketRegimeChanged",
        "ConfidenceIncreased",
        "ConfidenceDropped",
        "RiskIncreased",
        "CommitteeChanged",
    }
)


def is_telegram_eligible(event_type: str) -> bool:
    return event_type in TELEGRAM_ELIGIBLE_EVENT_TYPES


def detect_all_changes(previous: dict | None, current: dict) -> list[dict]:
    """Runs every change detector for one Watchdog cycle -- `previous`/
    `current` are WatchdogSnapshot-shaped dicts (or None if this is the
    first cycle ever, in which case nothing "changed" yet)."""
    if previous is None:
        return []
    events = [
        detect_regime_changed_event(previous.get("regime"), current.get("regime")),
        detect_trend_strength_change(
            previous.get("trend_strength_score"), current.get("trend_strength_score")
        ),
        detect_confidence_change(previous.get("confidence_score"), current.get("confidence_score")),
        detect_risk_change(previous.get("risk_score"), current.get("risk_score")),
        detect_liquidity_shift(previous.get("liquidity_score"), current.get("liquidity_score")),
        detect_volatility_spike(previous.get("volatility"), current.get("volatility")),
        detect_committee_change(
            previous.get("committee_decision"), current.get("committee_decision")
        ),
    ]
    return [e for e in events if e is not None]
