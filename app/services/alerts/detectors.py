"""Pure delta-detection functions for the Smart Alert Engine. Each takes a
"previous" and "current" already-persisted reading and returns an alert
dict (with a deterministic, documented `confidence_pct`) or `None` if
nothing alert-worthy happened. No detector fetches data itself -- that
keeps every function trivially unit-testable and keeps "what counts as a
change" fully separate from "where the data comes from".
"""

from app.services.common.scoring import clamp


def detect_regime_change(prev_regime: str | None, curr_regime: str) -> dict | None:
    if prev_regime is None or prev_regime == curr_regime:
        return None
    return {
        "alert_type": "regime_change",
        "message": f"Market regime changed: {prev_regime} -> {curr_regime}.",
        # A regime transition is a deterministic, rule-based state change (not a
        # noisy read), so it's always treated as high-confidence.
        "confidence_pct": 85,
        "data": {"prev_regime": prev_regime, "curr_regime": curr_regime},
    }


def detect_correlation_break(
    symbol_a: str,
    symbol_b: str,
    window_days: int,
    prev_correlation: float | None,
    curr_correlation: float,
    threshold: float = 0.3,
) -> dict | None:
    if prev_correlation is None:
        return None
    delta = curr_correlation - prev_correlation
    sign_flip = (prev_correlation > 0 > curr_correlation) or (
        prev_correlation < 0 < curr_correlation
    )
    if abs(delta) < threshold and not sign_flip:
        return None
    return {
        "alert_type": "correlation_break",
        "message": (
            f"{symbol_a} correlation with {symbol_b} ({window_days}d) has broken: "
            f"{prev_correlation:+.2f} -> {curr_correlation:+.2f}."
        ),
        # Scaled so a full swing from +1 to -1 (delta=2) reads as 100% confident.
        "confidence_pct": round(clamp(abs(delta) * 50)),
        "data": {
            "symbol_a": symbol_a,
            "symbol_b": symbol_b,
            "window_days": window_days,
            "prev_correlation": prev_correlation,
            "curr_correlation": curr_correlation,
        },
    }


def detect_dxy_reversal(
    prev_change_pct: float | None, curr_change_pct: float | None, min_magnitude: float = 0.1
) -> dict | None:
    if prev_change_pct is None or curr_change_pct is None:
        return None
    sign_flip = (prev_change_pct > 0 > curr_change_pct) or (prev_change_pct < 0 < curr_change_pct)
    if not sign_flip or abs(curr_change_pct) < min_magnitude:
        return None
    return {
        "alert_type": "dxy_reversal",
        "message": (
            f"Dollar Index reversed trend: {prev_change_pct:+.2f}% -> {curr_change_pct:+.2f}%."
        ),
        "confidence_pct": round(clamp(abs(curr_change_pct - prev_change_pct) * 20)),
        "data": {"prev_change_pct": prev_change_pct, "curr_change_pct": curr_change_pct},
    }


def detect_whale_accumulation(whale_snapshot: dict) -> dict | None:
    """Only ever fires if CoinGlass or Coinalyze is configured (see
    app/services/whales/engine.py) -- with neither configured, this
    honestly never triggers rather than inventing a positioning signal.
    Flags lopsided leveraged positioning (funding rate + long/short ratio),
    not on-chain accumulation/distribution -- that data isn't available."""
    if not whale_snapshot.get("available"):
        return None
    classification = whale_snapshot.get("classification")
    if classification not in ("long_heavy", "short_heavy"):
        return None
    return {
        "alert_type": "whale_positioning",
        "message": f"Derivatives positioning is {classification.replace('_', ' ')}.",
        "confidence_pct": 70,
        "data": whale_snapshot,
    }


def detect_etf_milestone(prev_classification: str | None, curr_etf_proxy: dict) -> dict | None:
    if not curr_etf_proxy.get("available"):
        return None
    classification = curr_etf_proxy.get("classification")
    if classification != "leaning_institutional_buying" or classification == prev_classification:
        return None
    items_analyzed = curr_etf_proxy.get("items_analyzed", 0)
    return {
        "alert_type": "etf_milestone",
        "message": (
            "ETF news-sentiment proxy turned bullish (institutional-buying lean) -- "
            "proxy only, not confirmed dollar flows."
        ),
        # More analyzed items backing the read raises confidence, capped well
        # below "certain" since this is explicitly a sentiment proxy.
        "confidence_pct": round(clamp(40 + items_analyzed * 2, upper=75)),
        "data": curr_etf_proxy,
    }


def detect_liquidity_change(
    prev_liquidity_score: int | None, curr_liquidity_score: int, threshold: int = 10
) -> dict | None:
    if prev_liquidity_score is None:
        return None
    delta = curr_liquidity_score - prev_liquidity_score
    if abs(delta) < threshold:
        return None
    direction = "improving" if delta > 0 else "deteriorating"
    return {
        "alert_type": "liquidity_change",
        "message": (
            f"Liquidity conditions {direction}: {prev_liquidity_score} -> {curr_liquidity_score}."
        ),
        "confidence_pct": round(clamp(abs(delta) * 5)),
        "data": {
            "prev_liquidity_score": prev_liquidity_score,
            "curr_liquidity_score": curr_liquidity_score,
        },
    }


def detect_fed_event_approaching(
    days_until_event: int, event_title: str, max_days: int = 7
) -> dict | None:
    if days_until_event < 0 or days_until_event > max_days:
        return None
    return {
        "alert_type": "fed_event_approaching",
        "message": f"Upcoming macro/policy event in {days_until_event}d: {event_title}.",
        "confidence_pct": 90,
        "data": {"days_until_event": days_until_event, "event_title": event_title},
    }
