"""NO-TRADE Engine -- a rule-based gate that can honestly say "don't
trade this", composing signals other engines already compute rather than
inventing a new scoring model. Never auto-executes or suggests position
sizing; this only classifies whether a symbol's current forecast is
trade-actionable right now (TRADE_OK vs NO_TRADE) and why.

Implemented checks (each a pure, independently testable function):
insufficient sample size, low direction probability, conflicting agents
(Consensus's own conflict_pct), extreme expected volatility, regime
uncertainty (Increment 1's regime_confidence_pct), poor forecast
calibration, an already-invalidated forecast (Increment 3), stale
reference data, and (POST-V9 Phase 8) insufficient expected edge.

POST-V9 Phase 2/8 hardening over the V9 version:
  - F-1: the low-probability gate and the expected-edge calculation now
    use ForecastEngine's `confidence.effective_confidence_pct` (sample-
    size- and Brier-score-discounted) when available, falling back to the
    raw `probability_pct` only when no discount could be computed --
    previously the raw, uncalibrated number reached the gate untouched.
  - F-3: `calibration_gap_pct` is now resolved from ForecastEngine's own
    real Prediction Quality Lab calibration buckets (the bucket matching
    this forecast's own confidence level), gated by that bucket's
    sample_sufficiency -- previously this parameter was always None in
    production (wired in the function signature, never fed real data).
  - F-4: a new `check_insufficient_edge` gates on
    `compute_expected_edge_pct` (probability's edge over a coin flip x
    expected move magnitude x risk:reward) rather than relying solely on
    independent hard thresholds -- a call that clears `check_low_probability`
    by a hair with a tiny expected move can still be gated here.

Explicitly NOT implemented here (require data/engines this module does
not have -- surfaced honestly, never faked): weak historical analog win
rate needs Similar Market Engine's own win-rate output plumbed through to
this composition layer; abnormal funding / excessive open interest need
WhaleIntelligenceEngine derivatives data. `evaluate_no_trade`'s signature
already accepts `historical_win_rate_pct` for when that lands.
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
# The same fixed 2:1 reward:risk convention app.services.portfolio.advisor's
# compute_atr_levels and the Trade Setup Engine already apply to every
# ATR-based stop/target in this project -- reused here as the default
# risk:reward assumption for the expected-edge estimate, not a fabricated
# per-symbol measurement. Override with a real value when one is available.
_DEFAULT_RISK_REWARD_RATIO = 2.0
_MIN_EXPECTED_EDGE_PCT = 0.3


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


def compute_expected_edge_pct(
    probability_pct: float | None,
    expected_move_pct: float | None,
    risk_reward_ratio: float = _DEFAULT_RISK_REWARD_RATIO,
) -> float | None:
    """Pure function: probability's edge over a coin flip (e.g. 70% ->
    0.20) x the magnitude of the expected move x the reward:risk ratio --
    a single heuristic score for "is this directional call, sized by how
    far it's expected to move and how favorable the reward:risk is, worth
    acting on", not a probabilistic expected-value guarantee. None (never
    guessed) when probability or expected move isn't available."""
    if probability_pct is None or expected_move_pct is None:
        return None
    probability_edge = (probability_pct - 50.0) / 100.0
    return round(probability_edge * abs(expected_move_pct) * risk_reward_ratio, 4)


def check_insufficient_edge(
    expected_edge_pct: float | None, min_expected_edge_pct: float = _MIN_EXPECTED_EDGE_PCT
) -> NoTradeReason | None:
    """None (never gated) when expected_edge_pct couldn't be computed --
    this check only fires on a real, if small, edge that's too thin, never
    on missing data (check_insufficient_sample/check_low_probability
    already cover the missing-data cases)."""
    if expected_edge_pct is None:
        return None
    if expected_edge_pct < min_expected_edge_pct:
        return NoTradeReason(
            "insufficient_edge",
            f"Expected edge {expected_edge_pct} below the minimum {min_expected_edge_pct} "
            "(probability edge x expected move x risk:reward too small to justify a trade)",
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
    expected_edge_pct: float | None = None,
    now: datetime | None = None,
    min_sample_size: int = _MIN_SAMPLE_SIZE,
    min_probability_pct: float = _MIN_PROBABILITY_PCT,
    max_dissent_pct: float = _MAX_DISSENT_PCT,
    max_volatility_pct: float = _MAX_VOLATILITY_PCT,
    min_regime_confidence_pct: float = _MIN_REGIME_CONFIDENCE_PCT,
    max_calibration_gap_pct: float = _MAX_CALIBRATION_GAP_PCT,
    max_stale_minutes: int = _MAX_STALE_MINUTES,
    min_historical_win_rate_pct: float = _MIN_HISTORICAL_WIN_RATE_PCT,
    min_expected_edge_pct: float = _MIN_EXPECTED_EDGE_PCT,
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
        check_insufficient_edge(expected_edge_pct, min_expected_edge_pct),
    )
    triggered = [c for c in checks if c is not None]
    return {
        "recommendation": "NO_TRADE" if triggered else "TRADE_OK",
        "reasons": [{"code": r.code, "description": r.description} for r in triggered],
    }


async def latest_regime_confidence_pct(
    session_factory: async_sessionmaker[AsyncSession],
) -> int | None:
    from app.database.models import MarketRegimeSnapshot

    async with session_factory() as session:
        row = await session.scalar(
            select(MarketRegimeSnapshot).order_by(MarketRegimeSnapshot.computed_at.desc()).limit(1)
        )
    return row.confidence_pct if row is not None else None


def resolve_calibration_gap_for_confidence(
    calibration_buckets: list[dict] | None, confidence_pct: float | None
) -> tuple[float | None, bool]:
    """Pure function: Prediction Quality Lab's own calibration buckets
    (already computed by ForecastEngine's PredictionQualityEngine.evaluate()
    call, never recomputed here) -> the calibration_gap_pct of whichever
    bucket THIS forecast's own confidence level falls into, plus whether
    that bucket's sample is large enough to trust (POST-V9 Phase 3's
    sample_sufficiency, "insufficient" = not trusted). (None, False) when
    there's no calibration data, no confidence to look up, or no bucket
    covers it -- never guessed."""
    if not calibration_buckets or confidence_pct is None:
        return None, False
    for bucket in calibration_buckets:
        low_str, high_str = bucket["confidence_bucket"].rstrip("%").split("-")
        low, high = float(low_str), float(high_str)
        if low <= confidence_pct <= high:
            sufficient = bucket.get("sample_sufficiency") != "insufficient"
            return bucket["calibration_gap_pct"], sufficient
    return None, False


def no_trade_result_from_payload(payload: dict, regime_confidence_pct: int | None) -> dict:
    """Pure function: extracts evaluate_no_trade()'s inputs from an
    already-computed ForecastEngine payload -- shared by
    evaluate_no_trade_for_symbol below and by the Trade Setup Engine (which
    already has a payload in hand and must not trigger a second, redundant
    ForecastEngine.compute() call just to get a NO-TRADE verdict).

    POST-V9 Phase 2/8 (F-1, F-3, F-4): gates on the calibration/sample-size-
    adjusted `effective_confidence_pct` when ForecastEngine computed one
    (falling back to the raw probability_pct only when it didn't), resolves
    a real calibration_gap_pct from ForecastEngine's own calibration
    buckets instead of leaving that check permanently inert, and computes
    an expected-edge score. `effective_probability_pct`, `calibration_gap_pct`,
    and `expected_edge_pct` are always included in the result for
    transparency, regardless of which gates they triggered."""
    consensus = payload.get("consensus") or {}
    reference_timestamp = payload.get("reference_timestamp")
    confidence = payload.get("confidence") or {}
    raw_probability_pct = payload.get("probability_pct")
    effective_probability_pct = confidence.get("effective_confidence_pct")
    gating_probability_pct = (
        effective_probability_pct if effective_probability_pct is not None else raw_probability_pct
    )

    calibration_gap_pct, calibration_sufficient = resolve_calibration_gap_for_confidence(
        payload.get("calibration"), gating_probability_pct
    )
    expected_edge_pct = compute_expected_edge_pct(
        gating_probability_pct, payload.get("expected_change_pct")
    )

    result = evaluate_no_trade(
        sample_size=payload.get("sample_size"),
        probability_pct=gating_probability_pct,
        dissent_pct=consensus.get("conflict_pct"),
        expected_volatility_pct=payload.get("expected_volatility_pct"),
        regime_confidence_pct=regime_confidence_pct,
        calibration_gap_pct=calibration_gap_pct if calibration_sufficient else None,
        forecast_status=payload.get("forecast_status"),
        reference_timestamp=(
            datetime.fromisoformat(reference_timestamp) if reference_timestamp else None
        ),
        expected_edge_pct=expected_edge_pct,
    )
    result["effective_probability_pct"] = effective_probability_pct
    result["calibration_gap_pct"] = calibration_gap_pct
    result["expected_edge_pct"] = expected_edge_pct
    return result


async def evaluate_no_trade_for_symbol(
    session_factory: async_sessionmaker[AsyncSession], symbol: str, horizon: str = "24h"
) -> dict | None:
    """Composes evaluate_no_trade()'s inputs entirely from engines that
    already exist -- ForecastEngine's own latest computation (probability,
    sample size, expected volatility, Consensus's conflict_pct, forecast
    status/reference timestamp, calibration buckets -- Increments 1 and 3,
    POST-V9 Phase 8) plus the latest regime's confidence_pct (Increment 1).
    Returns None when this symbol has no computable forecast at all (never
    a fabricated verdict). `historical_win_rate_pct` is still left
    unevaluated -- see this module's docstring for why.
    """
    from app.services.forecast.engine import build_forecast_engine

    payload = await build_forecast_engine().compute(symbol, horizon)
    if payload is None:
        return None

    result = no_trade_result_from_payload(
        payload, await latest_regime_confidence_pct(session_factory)
    )
    result["symbol"] = symbol.upper()
    result["horizon"] = horizon
    result["direction"] = payload.get("direction")
    result["probability_pct"] = payload.get("probability_pct")
    return result
