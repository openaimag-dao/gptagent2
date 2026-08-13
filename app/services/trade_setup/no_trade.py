"""NO-TRADE Engine -- a rule-based gate that can honestly say "don't
trade this", composing signals other engines already compute rather than
inventing a new scoring model. Never auto-executes or suggests position
sizing; this only classifies whether a symbol's current forecast is
trade-actionable right now (TRADE_OK vs NO_TRADE) and why.

Implemented checks (each a pure, independently testable function):
insufficient sample size, low direction probability, conflicting agents
(Consensus's own conflict_pct), extreme expected volatility, regime
uncertainty (Increment 1's regime_confidence_pct), poor forecast
calibration, an already-invalidated forecast (Increment 3), and stale
reference data.

Explicitly NOT implemented here (require data/engines this module does
not have -- surfaced honestly, never faked): poor risk/reward and weak
historical edge need real entry/stop/target levels and analog-match win
rates, which belong to the (not-yet-built) Trade Setup Engine; abnormal
funding / excessive open interest need WhaleIntelligenceEngine derivatives
data plumbed through to this composition layer. `evaluate_no_trade`'s
signature already accepts `historical_win_rate_pct` for when that lands.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

_MIN_SAMPLE_SIZE = 20
_MIN_PROBABILITY_PCT = 55.0
_MAX_DISSENT_PCT = 45.0
_MAX_VOLATILITY_PCT = 15.0
_MIN_REGIME_CONFIDENCE_PCT = 30.0
_MAX_CALIBRATION_GAP_PCT = 20.0
_MAX_STALE_MINUTES = 120
_MIN_HISTORICAL_WIN_RATE_PCT = 50.0


@dataclass(frozen=True)
class NoTradeReason:
    code: str
    description: str


def check_insufficient_sample(
    sample_size: int | None, min_sample_size: int = _MIN_SAMPLE_SIZE
) -> NoTradeReason | None:
    if sample_size is None or sample_size < min_sample_size:
        return NoTradeReason(
            "insufficient_data",
            f"Sample size {sample_size} below the minimum {min_sample_size}",
        )
    return None


def check_low_probability(
    probability_pct: float | None, min_probability_pct: float = _MIN_PROBABILITY_PCT
) -> NoTradeReason | None:
    if probability_pct is None:
        return NoTradeReason("insufficient_data", "No direction probability available")
    if probability_pct < min_probability_pct:
        return NoTradeReason(
            "low_probability",
            f"Direction probability {probability_pct}% below the minimum {min_probability_pct}%",
        )
    return None


def check_conflicting_agents(
    dissent_pct: float | None, max_dissent_pct: float = _MAX_DISSENT_PCT
) -> NoTradeReason | None:
    if dissent_pct is not None and dissent_pct > max_dissent_pct:
        return NoTradeReason(
            "conflicting_agents",
            f"Agent dissent {dissent_pct}% exceeds the maximum {max_dissent_pct}%",
        )
    return None


def check_extreme_volatility(
    expected_volatility_pct: float | None, max_volatility_pct: float = _MAX_VOLATILITY_PCT
) -> NoTradeReason | None:
    if expected_volatility_pct is not None and expected_volatility_pct > max_volatility_pct:
        return NoTradeReason(
            "extreme_volatility",
            f"Expected volatility {expected_volatility_pct}% exceeds "
            f"the maximum {max_volatility_pct}%",
        )
    return None


def check_regime_uncertainty(
    regime_confidence_pct: float | None,
    min_regime_confidence_pct: float = _MIN_REGIME_CONFIDENCE_PCT,
) -> NoTradeReason | None:
    if regime_confidence_pct is not None and regime_confidence_pct <= min_regime_confidence_pct:
        return NoTradeReason(
            "regime_uncertainty",
            f"Regime confidence {regime_confidence_pct} at or below "
            f"the minimum {min_regime_confidence_pct}",
        )
    return None


def check_poor_calibration(
    calibration_gap_pct: float | None, max_calibration_gap_pct: float = _MAX_CALIBRATION_GAP_PCT
) -> NoTradeReason | None:
    if calibration_gap_pct is not None and abs(calibration_gap_pct) > max_calibration_gap_pct:
        return NoTradeReason(
            "poor_calibration",
            f"Calibration gap {calibration_gap_pct}pp exceeds "
            f"the maximum {max_calibration_gap_pct}pp",
        )
    return None


def check_forecast_invalidated(forecast_status: str | None) -> NoTradeReason | None:
    if forecast_status == "INVALIDATED":
        return NoTradeReason(
            "forecast_invalidated", "The underlying forecast has since been invalidated"
        )
    return None


def check_stale_data(
    reference_timestamp: datetime | None,
    now: datetime | None = None,
    max_stale_minutes: int = _MAX_STALE_MINUTES,
) -> NoTradeReason | None:
    if reference_timestamp is None:
        return NoTradeReason("stale_data", "No reference timestamp available")
    now = now or datetime.now(UTC)
    age_minutes = (now - reference_timestamp).total_seconds() / 60
    if age_minutes > max_stale_minutes:
        return NoTradeReason(
            "stale_data",
            f"Reference data is {age_minutes:.0f} minutes old "
            f"(maximum {max_stale_minutes} minutes)",
        )
    return None


def check_weak_historical_edge(
    historical_win_rate_pct: float | None,
    min_historical_win_rate_pct: float = _MIN_HISTORICAL_WIN_RATE_PCT,
) -> NoTradeReason | None:
    if (
        historical_win_rate_pct is not None
        and historical_win_rate_pct < min_historical_win_rate_pct
    ):
        return NoTradeReason(
            "weak_historical_edge",
            f"Historical analog win rate {historical_win_rate_pct}% below "
            f"the minimum {min_historical_win_rate_pct}%",
        )
    return None


def evaluate_no_trade(
    *,
    sample_size: int | None,
    probability_pct: float | None,
    dissent_pct: float | None = None,
    expected_volatility_pct: float | None = None,
    regime_confidence_pct: float | None = None,
    calibration_gap_pct: float | None = None,
    forecast_status: str | None = None,
    reference_timestamp: datetime | None = None,
    historical_win_rate_pct: float | None = None,
    now: datetime | None = None,
    min_sample_size: int = _MIN_SAMPLE_SIZE,
    min_probability_pct: float = _MIN_PROBABILITY_PCT,
    max_dissent_pct: float = _MAX_DISSENT_PCT,
    max_volatility_pct: float = _MAX_VOLATILITY_PCT,
    min_regime_confidence_pct: float = _MIN_REGIME_CONFIDENCE_PCT,
    max_calibration_gap_pct: float = _MAX_CALIBRATION_GAP_PCT,
    max_stale_minutes: int = _MAX_STALE_MINUTES,
    min_historical_win_rate_pct: float = _MIN_HISTORICAL_WIN_RATE_PCT,
) -> dict:
    """Composes every check above into one TRADE_OK/NO_TRADE verdict.
    Any single triggered reason is enough to gate to NO_TRADE -- this
    system is explicitly allowed to say NO TRADE rather than being forced
    into always producing a directional call. A parameter left at None
    (data genuinely not available) is honestly skipped, never guessed."""
    checks = (
        check_insufficient_sample(sample_size, min_sample_size),
        check_low_probability(probability_pct, min_probability_pct),
        check_conflicting_agents(dissent_pct, max_dissent_pct),
        check_extreme_volatility(expected_volatility_pct, max_volatility_pct),
        check_regime_uncertainty(regime_confidence_pct, min_regime_confidence_pct),
        check_poor_calibration(calibration_gap_pct, max_calibration_gap_pct),
        check_forecast_invalidated(forecast_status),
        check_stale_data(reference_timestamp, now, max_stale_minutes),
        check_weak_historical_edge(historical_win_rate_pct, min_historical_win_rate_pct),
    )
    triggered = [c for c in checks if c is not None]
    return {
        "recommendation": "NO_TRADE" if triggered else "TRADE_OK",
        "reasons": [{"code": r.code, "description": r.description} for r in triggered],
    }


async def _latest_regime_confidence_pct(
    session_factory: async_sessionmaker[AsyncSession],
) -> int | None:
    from app.database.models import MarketRegimeSnapshot

    async with session_factory() as session:
        row = await session.scalar(
            select(MarketRegimeSnapshot).order_by(MarketRegimeSnapshot.computed_at.desc()).limit(1)
        )
    return row.confidence_pct if row is not None else None


async def evaluate_no_trade_for_symbol(
    session_factory: async_sessionmaker[AsyncSession], symbol: str, horizon: str = "24h"
) -> dict | None:
    """Composes evaluate_no_trade()'s inputs entirely from engines that
    already exist -- ForecastEngine's own latest computation (probability,
    sample size, expected volatility, Consensus's conflict_pct, forecast
    status/reference timestamp -- Increments 1 and 3) plus the latest
    regime's confidence_pct (Increment 1). Returns None when this symbol
    has no computable forecast at all (never a fabricated verdict).
    calibration_gap_pct and historical_win_rate_pct are left unevaluated
    here -- see this module's docstring for why.
    """
    from app.services.forecast.engine import build_forecast_engine

    payload = await build_forecast_engine().compute(symbol, horizon)
    if payload is None:
        return None

    consensus = payload.get("consensus") or {}
    reference_timestamp = payload.get("reference_timestamp")
    result = evaluate_no_trade(
        sample_size=payload.get("sample_size"),
        probability_pct=payload.get("probability_pct"),
        dissent_pct=consensus.get("conflict_pct"),
        expected_volatility_pct=payload.get("expected_volatility_pct"),
        regime_confidence_pct=await _latest_regime_confidence_pct(session_factory),
        forecast_status=payload.get("forecast_status"),
        reference_timestamp=(
            datetime.fromisoformat(reference_timestamp) if reference_timestamp else None
        ),
    )
    result["symbol"] = symbol.upper()
    result["horizon"] = horizon
    result["direction"] = payload.get("direction")
    result["probability_pct"] = payload.get("probability_pct")
    return result
