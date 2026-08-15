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
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.services.portfolio.advisor import compute_atr_levels
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


async def evaluate_trade_setup_for_symbol(
    session_factory: async_sessionmaker[AsyncSession], symbol: str, horizon: str = "24h"
) -> dict | None:
    """Computes one ForecastEngine payload and reuses it for both the
    NO-TRADE gate and the setup itself -- never recomputes the forecast
    twice. Returns None when this symbol has no computable forecast at all
    (never a fabricated setup)."""
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
    return setup.to_dict()
