"""Structured, machine-checkable forecast invalidation rules -- distinct
from the existing narrative `invalidation_risk` string (Committee's
weakest-agent callout, kept as-is elsewhere for backward compatibility;
see WatchdogSnapshot.consensus). A forecast becomes INVALIDATED when a
concrete, checkable condition fires: price crosses the forecast's own
invalidation_level in the direction that would falsify the call, or the
market regime it was made under has since changed. Both conditions are
evaluated from data the forecast (and the live market) already record --
never a new data source, never a guess.
"""

from dataclasses import dataclass
from typing import Any

_BULLISH_DIRECTIONS = frozenset({"Bullish", "Strong Bullish"})
_BEARISH_DIRECTIONS = frozenset({"Bearish", "Strong Bearish"})


@dataclass(frozen=True)
class InvalidationRule:
    rule_type: str
    description: str
    triggered: bool


def evaluate_price_invalidation(
    direction: str, invalidation_level: float | None, current_price: float | None
) -> InvalidationRule | None:
    """Triggers when price has moved past the forecast's own
    invalidation_level in the direction that would falsify a Bullish/
    Bearish call (e.g. a Bullish call's support-based invalidation_level
    being broken to the downside). None (not evaluated, not "not
    triggered") for a Neutral call or when the level/current price aren't
    available -- there is nothing checkable, so nothing is claimed.
    """
    if invalidation_level is None or current_price is None:
        return None
    if direction in _BULLISH_DIRECTIONS:
        triggered = current_price < invalidation_level
        side = "below"
    elif direction in _BEARISH_DIRECTIONS:
        triggered = current_price > invalidation_level
        side = "above"
    else:
        return None
    return InvalidationRule(
        rule_type="price_breaches_invalidation_level",
        description=f"Price moved {side} the invalidation level {invalidation_level:.4g}",
        triggered=triggered,
    )


def evaluate_regime_invalidation(
    regime_at_forecast: str | None, current_regime: str | None
) -> InvalidationRule | None:
    """Triggers when the market regime has changed since this forecast was
    made -- the regime-conditioned probability/analogues it was built on
    (see Increment 1/2) no longer describe the current market. None when
    either regime is unavailable, never a guessed comparison.
    """
    if regime_at_forecast is None or current_regime is None:
        return None
    triggered = regime_at_forecast != current_regime
    return InvalidationRule(
        rule_type="regime_changed",
        description=f"Regime changed from {regime_at_forecast} to {current_regime}",
        triggered=triggered,
    )


def evaluate_invalidation(
    direction: str,
    invalidation_level: float | None,
    current_price: float | None,
    regime_at_forecast: str | None,
    current_regime: str | None,
) -> dict[str, Any]:
    """Composes the individual rule checks into one status. INVALIDATED as
    soon as any evaluated rule triggers; ACTIVE otherwise -- including when
    no rule could be evaluated at all (e.g. a Neutral call, or missing
    regime data), since the absence of a checkable condition is not itself
    an invalidation.
    """
    rules = [
        rule
        for rule in (
            evaluate_price_invalidation(direction, invalidation_level, current_price),
            evaluate_regime_invalidation(regime_at_forecast, current_regime),
        )
        if rule is not None
    ]
    triggered = [rule for rule in rules if rule.triggered]
    return {
        "status": "INVALIDATED" if triggered else "ACTIVE",
        "checked_rules": [
            {"rule_type": r.rule_type, "description": r.description, "triggered": r.triggered}
            for r in rules
        ],
        "invalidation_reason": triggered[0].description if triggered else None,
    }
