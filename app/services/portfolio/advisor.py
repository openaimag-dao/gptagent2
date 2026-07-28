"""Portfolio Advisor -- turns already-computed Signal/Probability/ATR data
into an actionable BUY/SELL/HOLD recommendation with a documented,
deterministic stop-loss/take-profit/position-size. No new data source and
no LLM: reuses SignalEngine's bull/bear score, ProbabilityEngine's
empirical up/down/flat split for the specific symbol, and the Historical
Intelligence Engine's own ATR (Average True Range) for volatility-scaled
risk levels.

Important, honestly-documented limitation: `SignalEngine`'s net_score is a
macro/market-wide bull-bear read (NASDAQ/DXY/Gold/ETF-flow-proxy/Fed/VIX/
US10Y factors), not a per-symbol signal -- this project has no per-asset
technical signal engine. `net_score` is combined here with the symbol's
own empirical probability (which IS symbol-specific) as the closest thing
this project has to two independent reads to check for agreement on a
given symbol -- not a claim that the macro signal was computed "for" that
symbol.
"""

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import ProbabilitySnapshot, SignalSnapshot
from app.services.history.registry import find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.portfolio.engine import PortfolioEngine
from app.services.probability.engine import ProbabilityEngine
from app.services.signals.engine import SignalEngine

# Stop-loss set this many ATRs from the reference price -- a standard,
# volatility-scaled risk level (wider stop when the asset is naturally
# more volatile, tighter when it isn't), not an arbitrary fixed percentage.
_ATR_STOP_MULTIPLIER = 2.0
# Take-profit set at this multiple of the stop distance -- a fixed 2:1
# reward:risk ratio, documented and consistent for every recommendation.
_RISK_REWARD_RATIO = 2.0
# Default fraction of portfolio equity risked if the recommended position
# is stopped out.
_DEFAULT_RISK_PCT = 0.01


@dataclass(frozen=True)
class PortfolioAdvice:
    symbol: str
    timeframe: str
    recommendation: str  # "BUY" | "SELL" | "HOLD"
    reasoning: str
    signal_net_score: int
    probability: dict[str, int]
    entry_reference_price: float
    atr: float | None
    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    risk_reward_ratio: float | None = None
    position_size_quantity: float | None = None
    position_size_note: str | None = None

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "recommendation": self.recommendation,
            "reasoning": self.reasoning,
            "signal_net_score": self.signal_net_score,
            "probability": self.probability,
            "entry_reference_price": self.entry_reference_price,
            "atr": self.atr,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "risk_reward_ratio": self.risk_reward_ratio,
            "position_size_quantity": self.position_size_quantity,
            "position_size_note": self.position_size_note,
        }


def compute_advice(
    *,
    symbol: str,
    timeframe: str,
    close: float,
    atr: float | None,
    net_score: int,
    prob_up_pct: int,
    prob_down_pct: int,
    prob_flat_pct: int,
    portfolio_value: float | None = None,
    risk_pct: float = _DEFAULT_RISK_PCT,
) -> PortfolioAdvice:
    """Pure function: real, already-computed signal/probability/ATR/equity
    values -> a PortfolioAdvice. Never fabricates a number it wasn't given."""
    probs = {"up": prob_up_pct, "down": prob_down_pct, "flat": prob_flat_pct}
    dominant = max(probs, key=probs.get)

    if net_score > 0 and dominant == "up":
        recommendation = "BUY"
        agreement = "agrees with"
    elif net_score < 0 and dominant == "down":
        recommendation = "SELL"
        agreement = "agrees with"
    else:
        recommendation = "HOLD"
        agreement = (
            "disagrees with" if net_score != 0 and dominant != "flat" else "is inconclusive with"
        )

    signal_bias = "bullish" if net_score > 0 else "bearish" if net_score < 0 else "neutral"
    reasoning = (
        f"Signal Engine net score {net_score} ({signal_bias}) {agreement} the empirical "
        f"probability read (dominant: {dominant} at {probs[dominant]}%)."
    )

    stop_loss_price: float | None = None
    take_profit_price: float | None = None
    risk_reward_ratio: float | None = None
    position_size_quantity: float | None = None
    position_size_note: str | None = None

    if atr is not None and atr > 0 and recommendation in ("BUY", "SELL"):
        stop_distance = _ATR_STOP_MULTIPLIER * atr
        reward_distance = stop_distance * _RISK_REWARD_RATIO
        if recommendation == "BUY":
            stop_loss_price = round(close - stop_distance, 8)
            take_profit_price = round(close + reward_distance, 8)
        else:
            stop_loss_price = round(close + stop_distance, 8)
            take_profit_price = round(close - reward_distance, 8)
        risk_reward_ratio = _RISK_REWARD_RATIO

        if recommendation == "BUY" and portfolio_value:
            risk_amount = portfolio_value * risk_pct
            risk_per_unit = close - stop_loss_price
            if risk_per_unit > 0:
                position_size_quantity = round(risk_amount / risk_per_unit, 6)
                position_size_note = (
                    f"Sized to risk {risk_pct * 100:.1f}% of portfolio equity "
                    f"({risk_amount:.2f}) if stopped out at {stop_loss_price}."
                )

    return PortfolioAdvice(
        symbol=symbol,
        timeframe=timeframe,
        recommendation=recommendation,
        reasoning=reasoning,
        signal_net_score=net_score,
        probability=probs,
        entry_reference_price=close,
        atr=atr,
        stop_loss_price=stop_loss_price,
        take_profit_price=take_profit_price,
        risk_reward_ratio=risk_reward_ratio,
        position_size_quantity=position_size_quantity,
        position_size_note=position_size_note,
    )


class PortfolioAdvisorEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        signal_engine: SignalEngine,
        probability_engine: ProbabilityEngine,
        portfolio_engine: PortfolioEngine,
    ) -> None:
        self._session_factory = session_factory
        self._signal_engine = signal_engine
        self._probability_engine = probability_engine
        self._portfolio_engine = portfolio_engine

    async def advise(
        self,
        symbol: str,
        timeframe: Timeframe = Timeframe.DAILY,
        portfolio_id: int | None = None,
        risk_pct: float = _DEFAULT_RISK_PCT,
    ) -> PortfolioAdvice | None:
        config = find_symbol_config(symbol)
        if config is None or timeframe not in config.timeframes:
            return None

        rows = await get_series(self._session_factory, config.model, config.symbol, timeframe)
        if not rows:
            return None

        signal_snapshot: SignalSnapshot | None = await self._signal_engine.get_latest()
        probability_snapshot: (
            ProbabilitySnapshot | None
        ) = await self._probability_engine.get_latest(config.symbol, timeframe)
        if signal_snapshot is None or probability_snapshot is None:
            return None

        portfolio_value: float | None = None
        if portfolio_id is not None:
            health = await self._portfolio_engine.compute_health(portfolio_id)
            if not health.get("empty"):
                portfolio_value = health.get("total_value")

        latest = rows[-1]
        return compute_advice(
            symbol=config.symbol,
            timeframe=timeframe.value,
            close=float(latest.close),
            atr=float(latest.atr) if latest.atr is not None else None,
            net_score=signal_snapshot.net_score,
            prob_up_pct=probability_snapshot.prob_up_pct,
            prob_down_pct=probability_snapshot.prob_down_pct,
            prob_flat_pct=probability_snapshot.prob_flat_pct,
            portfolio_value=portfolio_value,
            risk_pct=risk_pct,
        )
