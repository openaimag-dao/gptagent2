"""Pure Portfolio Engine math -- no I/O, unit-testable. Position valuation,
exposure/diversification and the Portfolio Health Score composite. Drawdown
itself is computed by the caller via the existing
`app.services.backtest.metrics.compute_max_drawdown_pct` (reused, not
reimplemented) over a weighted daily return series.
"""

from app.services.common.scoring import clamp, weighted_average

CASH_SYMBOL = "CASH"

_HEALTH_WEIGHTS: dict[str, float] = {
    "data_completeness": 0.3,
    "diversification": 0.3,
    "risk": 0.4,
}


def value_position(quantity: float, price: float) -> float:
    return quantity * price


def unrealized_pnl_pct(entry_price: float | None, current_price: float) -> float | None:
    if entry_price is None or entry_price == 0:
        return None
    return round(100 * (current_price - entry_price) / entry_price, 4)


def compute_exposure(position_values: dict[str, float]) -> dict[str, float]:
    """symbol/class -> value in `position_values` becomes symbol/class -> %
    of total. Empty dict in, empty dict out (never divides by zero)."""
    total = sum(position_values.values())
    if total <= 0:
        return {}
    return {key: round(100 * value / total, 2) for key, value in position_values.items()}


def compute_diversification_score(exposure_by_class_pct: dict[str, float]) -> float | None:
    """0 (all-in-one-bucket) to 100 (evenly spread), via 1 - Herfindahl
    concentration index (HHI) on the exposure shares."""
    if not exposure_by_class_pct:
        return None
    shares = [pct / 100 for pct in exposure_by_class_pct.values()]
    hhi = sum(s**2 for s in shares)
    return round(clamp((1 - hhi) * 100))


def compute_risk_score(max_drawdown_pct: float | None) -> float | None:
    """Higher drawdown -> lower risk score. A 50% drawdown zeroes the score."""
    if max_drawdown_pct is None:
        return None
    return round(clamp(100 - abs(max_drawdown_pct) * 2))


def compute_health_score(
    data_completeness_pct: float,
    diversification_score: float | None,
    risk_score: float | None,
) -> int | None:
    return _round_or_none(
        weighted_average(
            {
                "data_completeness": data_completeness_pct,
                "diversification": diversification_score,
                "risk": risk_score,
            },
            _HEALTH_WEIGHTS,
        )
    )


def _round_or_none(value: float | None) -> int | None:
    return round(value) if value is not None else None
