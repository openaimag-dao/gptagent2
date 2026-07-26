"""Ranking Engine (V3 Phase 9): the same factor table the Signal Engine
already scores (app/services/signals/engine.py's FACTORS), restated as
Backtest condition DSL rules against stored history so each factor's real
predictive power can be measured -- not a second, parallel factor list.

"etf_inflow" has no history-table equivalent (Signal Engine reads it live
from a news-sentiment proxy, not a stored per-bar series) and is honestly
excluded here rather than backtested against a fabricated stand-in.
"""

from app.services.backtest.conditions import Condition

FACTOR_CONDITIONS: dict[str, Condition] = {
    "nasdaq_up": Condition(symbol="NASDAQ", field="return_pct", operator="gt", value=0.0),
    "dxy_down": Condition(symbol="DXY", field="return_pct", operator="lt", value=0.0),
    "gold_up": Condition(symbol="GOLD", field="return_pct", operator="gt", value=0.0),
    "fed_dovish": Condition(symbol="FEDRATE", field="return_pct", operator="lt", value=0.0),
    "vix_up": Condition(symbol="VIX", field="return_pct", operator="gt", value=0.0),
    "us10y_up": Condition(symbol="US10Y", field="return_pct", operator="gt", value=0.0),
}


def edge_pct(metrics: dict | None) -> float | None:
    """A factor's edge over a coin flip: |win_rate - 50|. None (not 0) when
    there's no usable backtest result -- "no edge" and "no data" are
    different honest states, never conflated."""
    if metrics is None or metrics.get("win_rate_pct") is None:
        return None
    return round(abs(metrics["win_rate_pct"] - 50), 2)
