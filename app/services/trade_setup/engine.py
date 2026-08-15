"""Trade Setup Engine -- combines ForecastEngine's own directional call
(probability, target price, key_levels already derived from
TechnicalAnalysisSnapshot's support/resistance) with
PortfolioAdvisorEngine's existing ATR-based stop-loss/take-profit formula
(reused via `compute_atr_levels`, never reimplemented) into one concrete
trade setup, gated by the NO-TRADE Engine (Increment 6) so this never
proposes a setup for a symbol NO-TRADE has already flagged as
non-actionable.

No new data source: entry is the forecast's own `current_price`; the
stop/target distance is the same ATR figure ForecastEngine already derived
(recovered from its own `expected_volatility_pct`, which is
`atr / current_price * 100`, rather than re-fetching history); invalidation/
breakout levels are the exact `key_levels` ForecastEngine already computed.

Deliberately not persisted to a table: like the NO-TRADE Engine, a trade
setup is a read-through composition over an already-versioned, already-
persisted forecast (`PriceForecastSnapshot`) -- there is nothing here that
outlives that forecast, so a separate append-only table would just be a
redundant snapshot of numbers already on record.

POST-V9 Phase 9 adds TRADE ECONOMICS, kept explicitly separate from the
SIGNAL QUALITY fields above (`probability_pct`, `conviction_tier`,
`recommendation`, `reasons` -- all forward-looking reads on today's
forecast): `backtest_trade_setup_for_symbol` walks this exact setup's
shape (same side, same stop/target distance as a % of entry) forward
through every historical daily bar for the symbol, using
`simulate_trade_outcome`'s bar-by-bar first-touch logic (there is no
existing walk-forward-with-stop/target code anywhere in this project to
reuse -- `alert_performance.engine.compute_excursions` measures a fixed
window's global max/min, not which of two price levels was touched
first) to see whether a trade shaped like this one would have hit its
target or its stop, then reuses `app.services.backtest.metrics`'s
existing win_rate/avg_win/avg_loss/expectancy/profit_factor statistics
(not reimplemented) over the resulting returns, adding only what that
module doesn't already cover: MAE/MFE and time-to-target/time-to-stop.
This measures the STRUCTURE of the trade (this side, this stop/target
shape, mechanically) working historically -- not a claim about today's
specific probability/signal quality, which stays exactly where it
already was.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.services.backtest.metrics import compute_backtest_metrics
from app.services.history.registry import find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.portfolio.advisor import compute_atr_levels
from app.services.quality.metrics import classify_calibration_reliability
from app.services.trade_setup.no_trade import (
    NoTradeReason,
    latest_regime_confidence_pct,
    no_trade_result_from_payload,
)

_BULLISH_DIRECTIONS = ("Bullish", "Strong Bullish")
_BEARISH_DIRECTIONS = ("Bearish", "Strong Bearish")


@dataclass(frozen=True)
class TradeSetup:
    symbol: str
    horizon: str
    recommendation: str  # "TRADE_OK" | "NO_TRADE"
    direction: str | None
    side: str | None  # "BUY" | "SELL" | None (no directional edge)
    entry_price: float | None
    stop_loss_price: float | None
    take_profit_price: float | None
    risk_reward_ratio: float | None
    invalidation_level: float | None
    breakout_level: float | None
    probability_pct: int | None
    conviction_tier: str | None
    reasons: list[dict]

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "horizon": self.horizon,
            "recommendation": self.recommendation,
            "direction": self.direction,
            "side": self.side,
            "entry_price": self.entry_price,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "risk_reward_ratio": self.risk_reward_ratio,
            "invalidation_level": self.invalidation_level,
            "breakout_level": self.breakout_level,
            "probability_pct": self.probability_pct,
            "conviction_tier": self.conviction_tier,
            "reasons": self.reasons,
        }


def direction_to_side(direction: str | None) -> str | None:
    """Pure function: ForecastEngine's own direction label -> a tradeable
    side, or None when the forecast itself has no directional lean
    ("Neutral") -- never a guessed side."""
    if direction in _BULLISH_DIRECTIONS:
        return "BUY"
    if direction in _BEARISH_DIRECTIONS:
        return "SELL"
    return None


def simulate_trade_outcome(
    entry_price: float,
    stop_loss_price: float,
    take_profit_price: float,
    side: str,
    window_rows: list,
) -> dict:
    """Pure function: one hypothetical trade's entry/stop/target/side ->
    what actually happened, walking `window_rows` (daily bars, ascending,
    starting the period AFTER entry) bar by bar and checking each one's
    high/low against both levels in the order they'd really be hit --
    first touch wins. This is the piece nothing else in the codebase
    provides: `alert_performance.engine.compute_excursions` measures a
    fixed window's global max/min, which can't say which of two price
    levels was touched first.

    A bar where both stop and target conditions are true at once (its
    daily range spans both prices) is undecidable from daily OHLC alone
    -- resolved as the stop, never overstating a win.

    Returns {"outcome": "target_hit"|"stop_hit"|"open",
    "realized_return_pct", "mae_pct", "mfe_pct", "days_to_target",
    "days_to_stop"}. "open" means neither level was touched before the
    window ran out; its realized_return_pct is mark-to-last-close, not a
    guessed resolution."""
    mae = 0.0
    mfe = 0.0
    for day, row in enumerate(window_rows, start=1):
        high = float(row.high)
        low = float(row.low)
        if side == "BUY":
            adverse = max(0.0, entry_price - low)
            favorable = max(0.0, high - entry_price)
            stop_hit = low <= stop_loss_price
            target_hit = high >= take_profit_price
        else:
            adverse = max(0.0, high - entry_price)
            favorable = max(0.0, entry_price - low)
            stop_hit = high >= stop_loss_price
            target_hit = low <= take_profit_price
        mae = max(mae, adverse)
        mfe = max(mfe, favorable)

        if stop_hit:
            exit_price = stop_loss_price
            outcome = "stop_hit"
        elif target_hit:
            exit_price = take_profit_price
            outcome = "target_hit"
        else:
            continue

        sign = 1 if side == "BUY" else -1
        return {
            "outcome": outcome,
            "realized_return_pct": round(100 * sign * (exit_price - entry_price) / entry_price, 4),
            "mae_pct": round(100 * mae / entry_price, 4),
            "mfe_pct": round(100 * mfe / entry_price, 4),
            "days_to_target": day if outcome == "target_hit" else None,
            "days_to_stop": day if outcome == "stop_hit" else None,
        }

    if not window_rows:
        return {
            "outcome": "open",
            "realized_return_pct": None,
            "mae_pct": None,
            "mfe_pct": None,
            "days_to_target": None,
            "days_to_stop": None,
        }
    sign = 1 if side == "BUY" else -1
    last_close = float(window_rows[-1].close)
    return {
        "outcome": "open",
        "realized_return_pct": round(100 * sign * (last_close - entry_price) / entry_price, 4),
        "mae_pct": round(100 * mae / entry_price, 4),
        "mfe_pct": round(100 * mfe / entry_price, 4),
        "days_to_target": None,
        "days_to_stop": None,
    }


def backtest_trade_setup_rule(
    side: str,
    stop_distance_pct: float,
    target_distance_pct: float,
    rows: list,
    max_holding_days: int,
) -> list[dict]:
    """Pure function: replays a trade shaped like THIS setup (same side,
    same stop/target distance as a percentage of entry) at every
    historical daily bar as a hypothetical entry, walking forward up to
    `max_holding_days` bars with `simulate_trade_outcome`. Skips entry
    points too close to the end of the available history to have any
    forward window (never fabricates a forward-looking outcome from data
    that doesn't exist yet). This measures whether the STRUCTURE of the
    trade (this side, this stop/target shape) has historically worked as
    a mechanical rule -- not a claim about today's specific probability,
    which stays exactly where it already lived (TradeSetup's own
    probability_pct/conviction_tier)."""
    outcomes = []
    for i, row in enumerate(rows):
        entry_price = float(row.close)
        if entry_price <= 0:
            continue
        window = rows[i + 1 : i + 1 + max_holding_days]
        if not window:
            continue
        if side == "BUY":
            stop = entry_price * (1 - stop_distance_pct / 100)
            target = entry_price * (1 + target_distance_pct / 100)
        else:
            stop = entry_price * (1 + stop_distance_pct / 100)
            target = entry_price * (1 - target_distance_pct / 100)
        outcomes.append(simulate_trade_outcome(entry_price, stop, target, side, window))
    return outcomes


def compute_trade_setup_expectancy(
    outcomes: list[dict],
    min_sample_size: int = 30,
    reliable_sample_size: int = 100,
) -> dict | None:
    """Pure function: a list of simulate_trade_outcome()-shaped results ->
    TRADE ECONOMICS, kept separate from TradeSetup's own SIGNAL QUALITY
    fields. Reuses app.services.backtest.metrics.compute_backtest_metrics
    for win_rate_pct/avg_win_pct/avg_loss_pct/expectancy_pct/profit_factor
    (not reimplemented here), adding only MAE/MFE and time-to-target/
    time-to-stop, which that module doesn't cover. None when there's
    nothing to score. `sample_sufficiency` uses the same small-sample
    honesty classification calibration buckets already use, so a 5-trade
    backtest is never read as a validated edge."""
    usable = [o for o in outcomes if o["realized_return_pct"] is not None]
    if not usable:
        return None

    returns = [o["realized_return_pct"] / 100 for o in usable]
    metrics = compute_backtest_metrics(returns) or {}
    target_hits = [o for o in usable if o["outcome"] == "target_hit"]
    stop_hits = [o for o in usable if o["outcome"] == "stop_hit"]
    mae_values = [o["mae_pct"] for o in usable if o["mae_pct"] is not None]
    mfe_values = [o["mfe_pct"] for o in usable if o["mfe_pct"] is not None]

    return {
        **metrics,
        "sample_count": len(usable),
        "sample_sufficiency": classify_calibration_reliability(
            len(usable), min_sample_size, reliable_sample_size
        ),
        "target_hit_count": len(target_hits),
        "stop_hit_count": len(stop_hits),
        "open_count": sum(1 for o in usable if o["outcome"] == "open"),
        "avg_mae_pct": (round(sum(mae_values) / len(mae_values), 4) if mae_values else None),
        "avg_mfe_pct": (round(sum(mfe_values) / len(mfe_values), 4) if mfe_values else None),
        "avg_days_to_target": (
            round(sum(o["days_to_target"] for o in target_hits) / len(target_hits), 2)
            if target_hits
            else None
        ),
        "avg_days_to_stop": (
            round(sum(o["days_to_stop"] for o in stop_hits) / len(stop_hits), 2)
            if stop_hits
            else None
        ),
    }


def build_trade_setup(
    *,
    symbol: str,
    horizon: str,
    forecast_payload: dict,
    no_trade_result: dict,
) -> TradeSetup:
    """Pure function: a ForecastEngine.compute() payload + an
    evaluate_no_trade()-shaped verdict -> one concrete trade setup. Never
    invents a direction the forecast didn't already call, never invents a
    stop/target the ATR formula didn't produce."""
    direction = forecast_payload.get("direction")
    side = direction_to_side(direction)
    current_price = forecast_payload.get("current_price")
    expected_volatility_pct = forecast_payload.get("expected_volatility_pct")
    atr = (
        expected_volatility_pct / 100 * current_price
        if expected_volatility_pct is not None and current_price is not None
        else None
    )

    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    risk_reward_ratio: float | None = None
    if side is not None and atr is not None and atr > 0 and current_price is not None:
        levels = compute_atr_levels(side, current_price, atr)
        stop_loss_price = levels["stop_loss_price"]
        take_profit_price = levels["take_profit_price"]
        risk_reward_ratio = levels["risk_reward_ratio"]

    reasons = list(no_trade_result.get("reasons", []))
    recommendation = no_trade_result.get("recommendation", "NO_TRADE")
    if side is None:
        recommendation = "NO_TRADE"
        no_edge = NoTradeReason(
            "no_directional_edge",
            f"Forecast direction is '{direction}' -- no tradeable side to set up",
        )
        reasons = [{"code": no_edge.code, "description": no_edge.description}, *reasons]

    key_levels = forecast_payload.get("key_levels") or {}
    return TradeSetup(
        symbol=symbol.upper(),
        horizon=horizon,
        recommendation=recommendation,
        direction=direction,
        side=side,
        entry_price=current_price,
        stop_loss_price=stop_loss_price,
        take_profit_price=take_profit_price,
        risk_reward_ratio=risk_reward_ratio,
        invalidation_level=key_levels.get("invalidation_level"),
        breakout_level=key_levels.get("breakout_level"),
        probability_pct=forecast_payload.get("probability_pct"),
        conviction_tier=(forecast_payload.get("confidence") or {}).get("tier"),
        reasons=reasons,
    )


async def backtest_trade_setup_for_symbol(
    session_factory: async_sessionmaker[AsyncSession], symbol: str, setup: TradeSetup
) -> dict | None:
    """POST-V9 Phase 9: I/O wrapper around backtest_trade_setup_rule +
    compute_trade_setup_expectancy -- historical TRADE ECONOMICS for a
    trade shaped like `setup`. None when the setup has no side/stop/target
    to backtest (NO_TRADE / no directional edge) or the symbol has no
    stored daily history yet (never a fabricated backtest)."""
    if setup.side is None or not setup.entry_price or not setup.stop_loss_price:
        return None
    if not setup.take_profit_price:
        return None
    config = find_symbol_config(symbol)
    if config is None:
        return None
    rows = await get_series(session_factory, config.model, config.symbol, Timeframe.DAILY)
    if len(rows) < 2:
        return None

    stop_distance_pct = 100 * abs(setup.entry_price - setup.stop_loss_price) / setup.entry_price
    target_distance_pct = 100 * abs(setup.take_profit_price - setup.entry_price) / setup.entry_price
    settings = get_settings()
    outcomes = backtest_trade_setup_rule(
        setup.side,
        stop_distance_pct,
        target_distance_pct,
        rows,
        settings.trade_setup_backtest_max_holding_days,
    )
    return compute_trade_setup_expectancy(
        outcomes,
        min_sample_size=settings.trade_setup_backtest_min_sample_size,
        reliable_sample_size=settings.trade_setup_backtest_reliable_sample_size,
    )


async def evaluate_trade_setup_for_symbol(
    session_factory: async_sessionmaker[AsyncSession], symbol: str, horizon: str = "24h"
) -> dict | None:
    """Computes one ForecastEngine payload and reuses it for both the
    NO-TRADE gate and the setup itself -- never recomputes the forecast
    twice. Returns None when this symbol has no computable forecast at all
    (never a fabricated setup). Also attaches `trade_economics` (POST-V9
    Phase 9) -- the setup's historical backtest, kept as a distinct key
    from the setup's own signal-quality fields above it."""
    from app.services.forecast.engine import build_forecast_engine

    payload = await build_forecast_engine().compute(symbol, horizon)
    if payload is None:
        return None

    no_trade_result = no_trade_result_from_payload(
        payload, await latest_regime_confidence_pct(session_factory)
    )
    setup = build_trade_setup(
        symbol=symbol, horizon=horizon, forecast_payload=payload, no_trade_result=no_trade_result
    )
    result = setup.to_dict()
    result["trade_economics"] = await backtest_trade_setup_for_symbol(
        session_factory, symbol, setup
    )
    return result
