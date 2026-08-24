"""Futures Simulator -- risk metrics and warnings. Pure function over the
account state and enriched position list the API layer already computes
(FuturesSimEngine.get_account_state / GET /api/simulator/positions'
live-enriched rows), zero I/O -- no new market-data or account queries,
just a derived view over data this app already has.

Task requirement: "permissive by default but warnings visible" -- this
module never blocks or rejects anything, it only classifies the account's
current state into HIGH_RISK / NEAR_LIQUIDATION / MARGIN_WARNING
warnings for the dashboard to surface."""

from app.config import get_settings


def _position_risk(position: dict) -> dict:
    """Pure function: one position's own notional and distance-to-
    liquidation, as a percent of its current mark price (how far the
    price would have to move, in the adverse direction, to liquidate this
    position) -- None when there's no liquidation price to measure
    against (a CROSS position that hasn't had one computed yet, see
    docs/FUTURES_SIMULATOR_MATH.md §8b's own documented deferral)."""
    mark_price = float(position["mark_price"])
    notional = float(position["quantity"]) * mark_price
    liquidation_price = position.get("liquidation_price")

    distance_pct = None
    if liquidation_price is not None and mark_price:
        liquidation_price = float(liquidation_price)
        if position["side"] == "LONG":
            distance_pct = round(100 * (mark_price - liquidation_price) / mark_price, 4)
        else:
            distance_pct = round(100 * (liquidation_price - mark_price) / mark_price, 4)

    return {
        "position_id": position["position_id"],
        "symbol": position["symbol"],
        "side": position["side"],
        "notional": notional,
        "distance_to_liquidation_pct": distance_pct,
    }


def _resolve_threshold(overrides: dict | None, key: str, default: float) -> float:
    """Task: Max Risk Settings (optional, per-account) -- an account-level
    override for one warning threshold, falling back to the global
    futures_sim_risk_* setting when the account hasn't set one (None)."""
    if overrides is not None:
        value = overrides.get(key)
        if value is not None:
            return float(value)
    return default


def compute_risk_metrics(
    account_state: dict,
    positions: list[dict],
    todays_realized_pnl: float = 0.0,
    risk_settings_overrides: dict | None = None,
) -> dict:
    """Task: Risk Metrics (margin ratio, distance to liquidation,
    position concentration, account drawdown, daily loss, largest
    position/exposure) with warnings (HIGH RISK / NEAR LIQUIDATION /
    MARGIN WARNING). `todays_realized_pnl` is the caller's own
    responsibility to compute (sum of today's closed trades' net_pnl) --
    this function only combines it with the account's current
    unrealized_pnl into a daily total, it does no trade-history query
    itself. `risk_settings_overrides` is the optional per-account Max
    Risk Settings dict (keys: high_margin_ratio_pct, near_liquidation_pct,
    margin_warning_available_pct, daily_loss_warning_pct) -- any key
    that's missing or None falls back to the matching global setting."""
    settings = get_settings()
    high_margin_ratio_threshold = _resolve_threshold(
        risk_settings_overrides,
        "high_margin_ratio_pct",
        settings.futures_sim_risk_high_margin_ratio_pct,
    )
    near_liquidation_threshold = _resolve_threshold(
        risk_settings_overrides,
        "near_liquidation_pct",
        settings.futures_sim_risk_near_liquidation_pct,
    )
    margin_warning_threshold = _resolve_threshold(
        risk_settings_overrides,
        "margin_warning_available_pct",
        settings.futures_sim_risk_margin_warning_available_pct,
    )
    daily_loss_warning_threshold = _resolve_threshold(
        risk_settings_overrides,
        "daily_loss_warning_pct",
        settings.futures_sim_risk_daily_loss_warning_pct,
    )

    equity = float(account_state["equity"])
    available_margin = float(account_state["available_margin"])
    margin_ratio_pct = account_state.get("margin_ratio")

    position_risks = [_position_risk(p) for p in positions]
    total_exposure = sum(p["notional"] for p in position_risks)
    for p in position_risks:
        p["concentration_pct"] = (
            round(100 * p["notional"] / total_exposure, 4) if total_exposure else None
        )
    largest_position = max(position_risks, key=lambda p: p["notional"]) if position_risks else None

    available_margin_pct = round(100 * available_margin / equity, 4) if equity else None
    daily_pnl = todays_realized_pnl + float(account_state["unrealized_pnl"])
    daily_loss_pct = round(-100 * daily_pnl / equity, 4) if equity and daily_pnl < 0 else None

    warnings = []
    if margin_ratio_pct is not None and margin_ratio_pct >= high_margin_ratio_threshold:
        warnings.append(
            {
                "level": "HIGH_RISK",
                "message": f"Margin ratio {margin_ratio_pct}% is elevated",
            }
        )
    if daily_loss_pct is not None and daily_loss_pct >= daily_loss_warning_threshold:
        warnings.append(
            {
                "level": "HIGH_RISK",
                "message": f"Today's loss is {daily_loss_pct}% of account equity",
            }
        )
    for p in position_risks:
        if (
            p["distance_to_liquidation_pct"] is not None
            and p["distance_to_liquidation_pct"] <= near_liquidation_threshold
        ):
            warnings.append(
                {
                    "level": "NEAR_LIQUIDATION",
                    "message": (
                        f"{p['symbol']} is {p['distance_to_liquidation_pct']}% from liquidation"
                    ),
                    "position_id": p["position_id"],
                }
            )
    if available_margin_pct is not None and available_margin_pct <= margin_warning_threshold:
        warnings.append(
            {
                "level": "MARGIN_WARNING",
                "message": f"Only {available_margin_pct}% of equity is available margin",
            }
        )

    return {
        "margin_ratio_pct": margin_ratio_pct,
        "available_margin_pct": available_margin_pct,
        "max_drawdown_pct": account_state.get("max_drawdown_pct"),
        "daily_pnl": daily_pnl,
        "daily_loss_pct": daily_loss_pct,
        "total_exposure": total_exposure,
        "open_position_count": len(position_risks),
        "largest_position": largest_position,
        "positions": position_risks,
        "warnings": warnings,
        "thresholds": {
            "high_margin_ratio_pct": high_margin_ratio_threshold,
            "near_liquidation_pct": near_liquidation_threshold,
            "margin_warning_available_pct": margin_warning_threshold,
            "daily_loss_warning_pct": daily_loss_warning_threshold,
        },
    }
