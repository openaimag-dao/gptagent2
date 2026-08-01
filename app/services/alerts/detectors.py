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
    """Only ever fires if a derivatives snapshot is actually available --
    CoinGlass (if configured) or CoinGecko's keyless fallback (see
    app/services/whales/engine.py). If both calls fail this cycle, this
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


def detect_flash_move(
    symbol: str, change_pct_24h: float | None, threshold: float = 8.0
) -> dict | None:
    """Flags an abnormal 24h price swing -- reuses AssetPrice.change_pct_24h,
    already computed by every price provider, no new data fetched."""
    if change_pct_24h is None or abs(change_pct_24h) < threshold:
        return None
    is_crash = change_pct_24h < 0
    return {
        "alert_type": "flash_crash" if is_crash else "flash_rally",
        "message": (
            f"{symbol} {'crashed' if is_crash else 'rallied'} {change_pct_24h:+.2f}% in 24h."
        ),
        # Scaled so a 2x threshold move reads as fully confident.
        "confidence_pct": round(clamp(50 + (abs(change_pct_24h) - threshold) * 5)),
        "data": {"symbol": symbol, "change_pct_24h": change_pct_24h, "threshold": threshold},
    }


def detect_funding_shift(
    prev_momentum_pct: float | None, curr_momentum_pct: float | None, threshold: float = 0.05
) -> dict | None:
    """Funding-rate momentum is already computed by the Feature Engine from
    the same whale/derivatives snapshots WhaleIntelligenceEngine persists --
    this only flags when it moves past a threshold, no new data source."""
    if prev_momentum_pct is None or curr_momentum_pct is None:
        return None
    delta = curr_momentum_pct - prev_momentum_pct
    if abs(delta) < threshold:
        return None
    direction = "rising" if delta > 0 else "falling"
    return {
        "alert_type": "funding_shift",
        "message": (
            f"Funding-rate momentum {direction}: "
            f"{prev_momentum_pct:+.3f}% -> {curr_momentum_pct:+.3f}%."
        ),
        "confidence_pct": round(clamp(abs(delta) * 400)),
        "data": {"prev_momentum_pct": prev_momentum_pct, "curr_momentum_pct": curr_momentum_pct},
    }


def detect_oi_spike(
    prev_oi_change_pct: float | None, curr_oi_change_pct: float | None, threshold: float = 10.0
) -> dict | None:
    """Open-interest change is already computed by the Feature Engine from
    the same derivatives snapshots -- flags an abnormal swing only."""
    if prev_oi_change_pct is None or curr_oi_change_pct is None:
        return None
    delta = curr_oi_change_pct - prev_oi_change_pct
    if abs(delta) < threshold:
        return None
    direction = "building" if delta > 0 else "unwinding"
    return {
        "alert_type": "oi_spike",
        "message": (
            f"Open interest {direction} sharply: "
            f"{prev_oi_change_pct:+.2f}% -> {curr_oi_change_pct:+.2f}%."
        ),
        "confidence_pct": round(clamp(50 + abs(delta))),
        "data": {
            "prev_oi_change_pct": prev_oi_change_pct,
            "curr_oi_change_pct": curr_oi_change_pct,
        },
    }


def detect_technical_alignment(alignment: dict | None, symbol: str = "BTC") -> dict | None:
    """v5.3: multiple technical indicators aligning at once -- reuses
    app.services.technical.signals.detect_high_confidence_alignment's
    result rather than recomputing it; this just translates that result
    into the Smart Alert Engine's detector contract as its 11th detector."""
    if alignment is None:
        return None
    signal = alignment["signal"]
    is_buy = signal == "HIGH_CONFIDENCE_BUY"
    reasons = ", ".join(alignment["reasons"])
    return {
        "alert_type": "high_confidence_buy" if is_buy else "high_confidence_sell",
        "message": (
            f"{symbol} HIGH CONFIDENCE {'BUY' if is_buy else 'SELL'} SIGNAL -- "
            f"{len(alignment['reasons'])} aligned technical signals: {reasons}."
        ),
        # More aligned reasons -> higher confidence; 2 is the floor
        # (detect_high_confidence_alignment never fires below that).
        "confidence_pct": round(clamp(60 + len(alignment["reasons"]) * 10)),
        "data": {"symbol": symbol, "signal": signal, "reasons": alignment["reasons"]},
    }
