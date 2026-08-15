"""Structured, machine-checkable forecast invalidation rules -- distinct
from the existing narrative `invalidation_risk` string (Committee's
weakest-agent callout, kept as-is elsewhere for backward compatibility;
see WatchdogSnapshot.consensus). A forecast becomes INVALIDATED when a
concrete, checkable condition fires: price crosses the forecast's own
invalidation_level in the direction that would falsify the call, or the
market regime it was made under has since changed. Both conditions are
evaluated from data the forecast (and the live market) already record --
never a new data source, never a guess.

POST-V9 Phase 17 adds `ForecastStatus` -- the full set of lifecycle
states `PriceForecastSnapshot.forecast_status` (a plain String(20)
column, not a DB-level enum; no migration needed since every value below
already fits the existing column and "ACTIVE"/"INVALIDATED" were already
in live use as bare strings) can actually hold -- plus the two state
transitions that were previously missing:
  - `status_after_superseded`: at most one ACTIVE forecast may exist per
    (symbol, horizon) at a time, so "the current forecast" is never
    ambiguous between two rows. Wired into ForecastEngine._persist,
    which supersedes prior ACTIVE rows for the same (symbol, horizon)
    before inserting the new one -- their own predicted values are never
    touched, only the lifecycle marker.
  - `status_after_grading`: grading (app.services.forecast.engine.
    grade_price_forecasts) must never silently erase an
    INVALIDATED/SUPERSEDED marker by resetting it to a generic graded
    status -- only a forecast that was STILL ACTIVE at grading time
    transitions to GRADED. One that was already INVALIDATED or
    SUPERSEDED keeps that status even after evaluated_at is filled in,
    so a caller can always tell "this forecast panned out AND was still
    considered live" from "this forecast panned out but had already been
    invalidated/superseded before its horizon even elapsed."
"""

import enum
from dataclasses import dataclass
from typing import Any

_BULLISH_DIRECTIONS = frozenset({"Bullish", "Strong Bullish"})
_BEARISH_DIRECTIONS = frozenset({"Bearish", "Strong Bearish"})


class ForecastStatus(str, enum.Enum):
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"
    # A newer forecast_version was computed for the same (symbol,
    # horizon) while this one was still ACTIVE.
    SUPERSEDED = "SUPERSEDED"
    # This forecast's horizon elapsed and it was graded
    # (direction_correct/error_pct/etc filled in) while it was still
    # ACTIVE. The spec's "EXPIRED/GRADABLE" concept, named GRADED since
    # in this codebase grading happens synchronously with the status
    # transition, not as a separate "became eligible" step.
    GRADED = "GRADED"


def status_after_superseded(current_status: str) -> str:
    """Pure function: POST-V9 Phase 17. Only a still-ACTIVE forecast
    transitions to SUPERSEDED when a newer forecast_version is computed
    for the same (symbol, horizon) -- one that's already
    INVALIDATED/GRADED keeps its own terminal status untouched, since it
    was already not "the active one"."""
    if current_status == ForecastStatus.ACTIVE.value:
        return ForecastStatus.SUPERSEDED.value
    return current_status


def status_after_grading(current_status: str) -> str:
    """Pure function: POST-V9 Phase 17. Only a still-ACTIVE forecast
    transitions to GRADED when its horizon elapses and it gets scored;
    one that was already INVALIDATED or SUPERSEDED before grading keeps
    that status -- grading fills in realized_price/direction_correct/etc,
    it never downgrades or erases the lifecycle marker that was already
    there."""
    if current_status == ForecastStatus.ACTIVE.value:
        return ForecastStatus.GRADED.value
    return current_status


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
