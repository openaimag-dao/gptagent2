"""AI Forecast Center -- the Overview page's hero card. Composes a $ price
target, a price path, a bucketed probability distribution, and a Confidence
Breakdown entirely out of numbers other engines already compute:

- The price target/path/distribution are a transparent, deterministic
  statistical model over two real already-computed inputs --
  `ProbabilityEngine`'s empirical `avg_forward_return_pct` for the requested
  horizon (mean) and ATR (volatility proxy, the same $-band primitive
  Portfolio Advisor already uses for stop/take-profit) -- never an invented
  or LLM-guessed number. See `compute_probability_distribution`'s docstring
  for the exact normal-approximation formula.
- Regime/risk/consensus/committee context is read straight off the latest
  `WatchdogSnapshot` (regime, risk_score, confidence_score, volatility,
  consensus vote tally, committee decision) rather than re-invoking
  Consensus/Committee/Regime/GlobalScore from scratch -- WatchdogSnapshot's
  own docstring already establishes "never duplicate calculations already
  performed by Replay/Committee/Consensus/Scenario/Risk" and this engine
  follows that.
- Confidence Breakdown rows are honestly gated on real data availability:
  On-chain is always reported "unavailable" (OnChainIntelligenceEngine is a
  documented no-data-source scaffold) rather than a fabricated number, and
  Whale confidence is only shown when CoinGlass/CoinGecko derivatives data
  actually came back this cycle.
"""

import logging
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.database.models import (
    AgentForecast,
    EconomicCalendarEvent,
    MarketRegimeSnapshot,
    PriceForecastSnapshot,
    WatchdogSnapshot,
)
from app.services.agents.pattern_agent import _recency_weighted_direction
from app.services.alert_performance.engine import compute_baseline_return_pct
from app.services.analysis.correlation import CorrelationEngine
from app.services.analysis.regime import MarketRegime, RegimeDetector, build_regime_index
from app.services.analysis.report import derive_risk_level
from app.services.backtest.metrics import compute_max_drawdown_pct
from app.services.calendar.engine import EconomicCalendarEngine
from app.services.common.scoring import center_scaled
from app.services.conviction.engine import classify_conviction
from app.services.data_quality.engine import assess_symbol_quality, compute_data_quality_score
from app.services.explanation.engine import ExplanationEngine
from app.services.forecast.invalidation import (
    ForecastStatus,
    evaluate_invalidation,
    status_after_grading,
    status_after_superseded,
)
from app.services.history.registry import find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.market.repository import MarketRepository
from app.services.onchain.engine import OnChainIntelligenceEngine
from app.services.patterns.engine import PatternEngine
from app.services.probability.engine import ProbabilityEngine
from app.services.quality.engine import PredictionQualityEngine
from app.services.quality.metrics import classify_calibration_reliability
from app.services.sentiment.engine import SentimentEngine
from app.services.technical.engine import TechnicalAnalysisEngine
from app.services.whales.engine import WhaleIntelligenceEngine

logger = logging.getLogger(__name__)

# horizon label -> horizon_periods on Timeframe.DAILY (which IS calendar
# days), so 24h/3d/7d/30d need no new multi-horizon engine -- just four
# distinct `horizon` values on the same ProbabilityEngine.
HORIZONS: dict[str, int] = {"24h": 1, "3d": 3, "7d": 7, "30d": 30}

# Final Audit (Phase 22, model versioning): ForecastEngine.compute() is a
# fixed deterministic formula (price target from ProbabilityEngine's
# empirical avg_forward_return_pct + ATR, confidence from the fixed
# _confidence_breakdown() sources above) -- not a periodically-retrained
# ML model. There is therefore exactly one honest "version" concept this
# codebase can support: a human-bumped tag for which revision of that
# formula produced a given PriceForecastSnapshot row, persisted as
# `model_version` at forecast-creation time. Bump this string by hand
# whenever a change to compute()/_confidence_breakdown()/the price-target
# math actually changes forecast OUTPUTS for the same inputs -- never on
# an unrelated refactor. Do NOT add separate feature_version/
# config_version/data_version constants alongside this: none of those are
# independently versioned anywhere in this codebase today, so they would
# always read "1" and carry zero real information -- exactly the kind of
# fabricated instrumentation this project's own rules forbid.
FORECAST_MODEL_VERSION = "1.0"


def compute_price_target(current_price: float, avg_forward_return_pct: float) -> float:
    """Pure function: the one real empirical mean forward return this
    project has for the symbol/horizon, applied to the current price. Not a
    second model -- the exact same number ProbabilityEngine already
    computed, just expressed in $ instead of %."""
    return current_price * (1 + avg_forward_return_pct / 100)


def compute_price_path(
    current_price: float,
    avg_forward_return_pct: float,
    fractions: tuple[float, ...] = (0.25, 0.5, 0.75, 1.0),
) -> list[dict]:
    """Pure function: interpolates the same empirical mean return across
    checkpoints of the horizon using sqrt-of-time scaling (the standard
    assumption that a random walk's variance grows linearly with time, so
    its scale grows with the square root) -- a deterministic extrapolation
    of one real number, not a fabricated path."""
    path = []
    for fraction in fractions:
        scaled_return_pct = avg_forward_return_pct * math.sqrt(fraction)
        price = current_price * (1 + scaled_return_pct / 100)
        path.append(
            {
                "fraction": fraction,
                "price": round(price, 8),
                "change_pct": round(scaled_return_pct, 4),
            }
        )
    return path


def _normal_mean_and_std(
    current_price: float, avg_forward_return_pct: float, atr: float | None
) -> tuple[float, float] | None:
    """Pure function: the one shared (mean_price, std) pair every normal-
    approximation calculation in this engine is built from -- mean is the
    empirically-observed forward return already computed by
    ProbabilityEngine, std is ATR (this project's one real $-volatility
    primitive). None (never a guessed pair) when ATR isn't available."""
    if atr is None or atr <= 0 or current_price <= 0:
        return None
    return current_price * (1 + avg_forward_return_pct / 100), atr


def compute_probability_distribution(
    current_price: float, avg_forward_return_pct: float, atr: float | None
) -> list[dict]:
    """Pure function: a normal approximation over the price target -- mean
    is the empirically-observed forward return already computed by
    ProbabilityEngine, standard deviation is ATR (this project's one real
    $-volatility primitive) -- not a black-box probability, an explicit,
    documented statistical model over two real inputs. Returns [] (never a
    guessed distribution) when ATR isn't available.

    Four buckets, edges at target +-0.5*ATR and +-1.5*ATR, probability mass
    via the standard normal CDF (`math.erf`, stdlib -- no new dependency)."""
    mean_and_std = _normal_mean_and_std(current_price, avg_forward_return_pct, atr)
    if mean_and_std is None:
        return []
    mean_price, std = mean_and_std

    def cdf(x: float) -> float:
        return 0.5 * (1 + math.erf((x - mean_price) / (std * math.sqrt(2))))

    upper_edge = mean_price + 1.5 * std
    mid_edge = mean_price + 0.5 * std
    low_edge = mean_price - 0.5 * std

    return [
        {
            "label": f"Above {upper_edge:.2f}",
            "probability_pct": round((1 - cdf(upper_edge)) * 100, 1),
        },
        {
            "label": f"{mid_edge:.2f} - {upper_edge:.2f}",
            "probability_pct": round((cdf(upper_edge) - cdf(mid_edge)) * 100, 1),
        },
        {
            "label": f"{low_edge:.2f} - {mid_edge:.2f}",
            "probability_pct": round((cdf(mid_edge) - cdf(low_edge)) * 100, 1),
        },
        {
            "label": f"Below {low_edge:.2f}",
            "probability_pct": round(cdf(low_edge) * 100, 1),
        },
    ]


def compute_prediction_range(
    current_price: float, avg_forward_return_pct: float, atr: float | None
) -> dict | None:
    """Pure function: Upper/Lower Bound of the same normal approximation
    `compute_probability_distribution` already builds its outer bucket
    edges from (+-1.5*ATR around the empirical mean) -- reused here as an
    explicit range rather than re-derived. None when ATR isn't available."""
    mean_and_std = _normal_mean_and_std(current_price, avg_forward_return_pct, atr)
    if mean_and_std is None:
        return None
    mean_price, std = mean_and_std
    return {
        "upper_bound": round(mean_price + 1.5 * std, 8),
        "lower_bound": round(mean_price - 1.5 * std, 8),
    }


def compute_scenario_cases(
    current_price: float,
    avg_forward_return_pct: float,
    atr: float | None,
    prob_up_pct: int,
    prob_down_pct: int,
    prob_flat_pct: int,
    effective_confidence_pct: float,
) -> dict | None:
    """Pure function: Bull/Base/Bear cases over the exact same real inputs
    the rest of this engine already computes -- no second forecasting
    model. Base Case's target is identical to `compute_price_target`
    (today's single target_price); Bull/Bear are the same mean +-1*ATR the
    normal approximation already treats as "one volatility band away".
    Each case's own probability is ProbabilityEngine's own real prob_up/
    down/flat_pct (already sums to 100 -- not re-derived). Confidence is
    `effective_confidence_pct` (the conviction already computed for this
    forecast) scaled down proportionally for the two non-dominant cases,
    so the dominant case's confidence matches today's single forecast
    confidence exactly, and the others reflect their lower relative
    likelihood -- not a separately invented number. None when ATR isn't
    available (no volatility band to build Bull/Bear off of)."""
    mean_and_std = _normal_mean_and_std(current_price, avg_forward_return_pct, atr)
    if mean_and_std is None:
        return None
    base_target, std = mean_and_std
    dominant_prob = max(prob_up_pct, prob_down_pct, prob_flat_pct)

    def _case(target_price: float, probability_pct: int) -> dict:
        expected_return_pct = round(100 * (target_price - current_price) / current_price, 4)
        confidence_pct = (
            round(effective_confidence_pct * probability_pct / dominant_prob)
            if dominant_prob > 0
            else None
        )
        return {
            "target_price": round(target_price, 8),
            "probability_pct": probability_pct,
            "expected_return_pct": expected_return_pct,
            "confidence_pct": confidence_pct,
        }

    return {
        "bull_case": _case(base_target + std, prob_up_pct),
        "base_case": _case(base_target, prob_flat_pct),
        "bear_case": _case(base_target - std, prob_down_pct),
    }


# Trailing daily returns beyond this many days add noise without adding
# signal for a 24h-72h forecast horizon -- the same "recent window" framing
# ATR/RSI already use, applied to drawdown instead of volatility/momentum.
_DRAWDOWN_LOOKBACK_DAYS = 30


def compute_expected_max_drawdown_pct(
    returns: list[float | None], lookback: int = _DRAWDOWN_LOOKBACK_DAYS
) -> float | None:
    """Pure function: real trailing daily `return_pct` history (already
    fractions, e.g. 0.02 = +2%, from HistoryTimeframe.DAILY rows) fed
    straight into `compute_max_drawdown_pct` (app/services/backtest/
    metrics.py) -- the same peak-to-trough drawdown Backtest/Portfolio
    already compute, applied to a new input, not a new formula. None when
    there's no real trailing history to measure."""
    trailing = [r for r in returns[-lookback:] if r is not None]
    if not trailing:
        return None
    return compute_max_drawdown_pct(trailing)


# How many percentage points of real signed momentum map to a full swing
# from center -- same per-percent scaling convention as GlobalScoreEngine's
# own fear_score (scale=4.0 off VIX change); momentum typically moves in a
# narrower band than VIX, so a slightly larger scale is used here.
_MOMENTUM_SCALE = 5.0


def compute_momentum_score(momentum_pct: float | None) -> float:
    """Pure function: TechnicalAnalysisSnapshot's own real signed momentum
    (% change, already computed by app/services/technical/scoring.py) ->
    a 0-100 score centered at 50, via the same `center_scaled` primitive
    every other centered composite score in this project (fear/greed/
    liquidity/macro_pressure) already uses. 50 (neutral) when momentum
    isn't available -- never a guessed direction."""
    return center_scaled(momentum_pct, scale=_MOMENTUM_SCALE)


def classify_direction_label(prob_up_pct: int, prob_down_pct: int) -> str:
    """Pure function: Strong Bullish...Strong Bearish over the net
    probability spread -- the same label-composition style
    `CommitteeVerdict`/`ConsensusResult` already use, just for this
    engine's own up-vs-down spread rather than an agent vote tally."""
    net = prob_up_pct - prob_down_pct
    if net >= 40:
        return "Strong Bullish"
    if net >= 15:
        return "Bullish"
    if net <= -40:
        return "Strong Bearish"
    if net <= -15:
        return "Bearish"
    return "Neutral"


# ADX (trend_strength) >= this is a classically "trending" market; a
# TechnicalAnalysisSnapshot.volatility (ATR as %-of-price, scaled 0-100 by
# app/services/technical/scoring.py) at or above this is unusually volatile
# for this project's data; at or below the compression threshold is unusually
# tight. Presentation-only thresholds over already-computed scores -- no new
# detection logic.
_TRENDING_ADX = 40.0
_HIGH_VOLATILITY_SCORE = 60.0
_COMPRESSION_VOLATILITY_SCORE = 15.0

_REGIME_LABELS: dict[MarketRegime, str] = {
    MarketRegime.ACCUMULATION: "Accumulation",
    MarketRegime.DISTRIBUTION: "Distribution",
    MarketRegime.CAPITULATION: "Capitulation",
    MarketRegime.LIQUIDITY_EXPANSION: "Expansion",
    MarketRegime.LIQUIDITY_CONTRACTION: "Compression",
}


def derive_regime_label(
    regime: MarketRegime | None, volatility: float | None, trend_strength: float | None
) -> str:
    """Pure function: presentation-only mapping of the existing
    `MarketRegime` enum plus TechnicalAnalysisEngine's own volatility/ADX
    scores onto the spec's Trending/Range/High Volatility/Accumulation/
    Distribution/Capitulation/Expansion/Compression labels. No new regime
    detection -- every one of these is read off a number another engine
    already computed this cycle."""
    if volatility is not None and volatility >= _HIGH_VOLATILITY_SCORE:
        return "High Volatility"
    if regime is not None and regime in _REGIME_LABELS:
        return _REGIME_LABELS[regime]
    if trend_strength is not None and trend_strength >= _TRENDING_ADX:
        return "Trending"
    if volatility is not None and volatility <= _COMPRESSION_VOLATILITY_SCORE:
        return "Compression"
    return "Range"


def derive_risk_meter(risk_score: int | None, regime: MarketRegime | None) -> str:
    """Pure function: extends `derive_risk_level` (app/services/analysis/
    report.py) with a fourth "Extreme" tier for the Forecast Center's own
    risk gauge, without touching that function's existing three-tier
    contract -- it's read by /api/risk, Telegram, and Reports today with
    tests pinned to exactly "high"/"low"/"moderate"."""
    if regime is None:
        return "Unknown"
    level = derive_risk_level(regime)
    if level == "high" and risk_score is not None and risk_score >= 85:
        return "Extreme"
    return level.capitalize()


@dataclass(frozen=True)
class ConfidenceRow:
    name: str
    confidence_pct: int | None  # None = honestly unavailable, never a forced number


def _distance_from_neutral(score: int | None) -> int | None:
    """0-100 confidence proxy from a 0-100 bullish/bearish balance score:
    how far from an uninformative 50 it sits, scaled back to 0-100. Used for
    SentimentEngine's own score fields -- not a new measurement, a
    reprojection of one that already exists."""
    if score is None:
        return None
    return round(min(100.0, abs(score - 50) * 2))


def _whale_confidence(snapshot: dict) -> int | None:
    """0-100 confidence proxy from real derivatives positioning data: how
    far the long/short ratio or funding rate sits from balanced, scaled
    against this engine's own classification thresholds
    (app/services/whales/engine.py's _RATIO_HIGH/_classify). None
    (unavailable) when CoinGlass/CoinGecko returned nothing this cycle."""
    if not snapshot.get("available"):
        return None
    ratio = snapshot.get("long_short_ratio")
    funding = snapshot.get("funding_rate")
    if ratio is not None:
        return round(min(100.0, abs(ratio - 1.0) / 0.5 * 100))
    if funding is not None:
        return round(min(100.0, abs(funding) / 0.0005 * 100))
    return None


def _onchain_confidence(snapshot: dict) -> int | None:
    """0-100 confidence proxy from how many of OnChainIntelligenceEngine's
    metrics actually came back populated. Always None today --
    `OnChainIntelligenceEngine` is a documented no-data-source scaffold
    (`available` is always False, every metric is always None) -- but
    written against the real `metrics` dict so this activates honestly, on
    its own, the day a real on-chain provider is wired in, with no change
    needed here."""
    if not snapshot.get("available"):
        return None
    metrics = snapshot.get("metrics") or {}
    if not metrics:
        return None
    populated = sum(1 for v in metrics.values() if v is not None)
    return round(100 * populated / len(metrics))


def _correlation_confidence(correlations: list, symbol: str) -> int | None:
    """0-100 confidence proxy from real rolling Pearson correlations: the
    average absolute 30-day correlation strength across every pair
    involving this symbol. None when no 30-day correlation has been
    computed for this symbol yet."""
    matches = [
        abs(float(c.correlation))
        for c in correlations
        if c.window_days == 30 and symbol in (c.symbol_a, c.symbol_b)
    ]
    if not matches:
        return None
    return round(min(100.0, (sum(matches) / len(matches)) * 100))


# Below this many graded forecasts, this symbol/horizon's own average error
# is too noisy to act on -- treated the same as "no track record yet,"
# never as evidence of poor accuracy. Mirrors
# app/services/conviction/engine.py's identical _MIN_QUALITY_SAMPLE_SIZE
# reasoning, applied to price-forecast error instead of Brier score.
_MIN_TRACK_RECORD_SAMPLE_SIZE = 10


def price_forecast_quality_multiplier(
    avg_abs_error_pct: float | None,
    evaluated_count: int | None,
    expected_volatility_pct: float | None,
    min_sample_size: int = _MIN_TRACK_RECORD_SAMPLE_SIZE,
) -> float | None:
    """Pure function: a symbol/horizon's own historical average |error%| ->
    a 0.0-1.0 discount, or None when there isn't enough graded history to
    judge yet (mirrors classify_conviction's Brier-score fold-in, but for
    price-target accuracy instead of direction calibration).

    The "no better than noise" baseline is this forecast's own
    `expected_volatility_pct` (ATR as %-of-price) -- a real already-computed
    number, not an arbitrary constant: a price target that's on average
    off by more than the symbol's own typical daily move carries no more
    information than guessing within its natural volatility band. 0% error
    -> 1.0; error at or beyond the volatility band -> 0.0."""
    if (
        avg_abs_error_pct is None
        or evaluated_count is None
        or evaluated_count < min_sample_size
        or expected_volatility_pct is None
        or expected_volatility_pct <= 0
    ):
        return None
    return round(max(0.0, min(1.0, 1 - avg_abs_error_pct / expected_volatility_pct)), 3)


_DIRECTION_SIGN: dict[str, int] = {
    "Strong Bullish": 1,
    "Bullish": 1,
    "Neutral": 0,
    "Bearish": -1,
    "Strong Bearish": -1,
}

# Forecast Intelligence Upgrade: which of the 4 existing HORIZONS group
# into each read -- this project has no 1H/4H forecast data (ForecastEngine
# only computes on the DAILY timeframe today), so "short/medium/long" here
# means 24h / 3d+7d / 30d, not the intraday granularity a generic spec
# might assume. Documented as a known limitation rather than silently
# reinterpreted.
_HORIZON_GROUPS: dict[str, tuple[str, ...]] = {
    "short_term": ("24h",),
    "medium_term": ("3d", "7d"),
    "long_term": ("30d",),
}


def _group_direction_label(directions: dict[str, str], horizons: tuple[str, ...]) -> str | None:
    signs = [_DIRECTION_SIGN[directions[h]] for h in horizons if h in directions]
    if not signs:
        return None
    avg = sum(signs) / len(signs)
    if avg > 0.25:
        return "Bullish"
    if avg < -0.25:
        return "Bearish"
    return "Neutral"


def compute_horizon_consistency(directions: dict[str, str]) -> dict | None:
    """Pure function: Forecast Intelligence Upgrade -- Multi-Horizon
    Consistency. `directions` maps horizon label ("24h"/"3d"/"7d"/"30d")
    to this project's own direction label (Strong Bullish..Strong
    Bearish), read straight from each horizon's own already-computed
    PriceForecastSnapshot.direction -- no new classification, just a
    cross-horizon comparison of labels that already exist.

    Horizons are never forced to agree: a genuine short-term-bullish /
    long-term-bearish split is reported as such, not smoothed into a
    single number. `consistency_pct` is the fraction of all horizon PAIRS
    whose direction sign agrees (Bullish/Strong Bullish vs Bearish/Strong
    Bearish are opposite signs; Neutral is its own sign) -- a real,
    checkable measurement of how much the horizons actually agree, not an
    opinion.

    None when there are fewer than 2 known horizons to compare --
    "consistency" is meaningless for a single data point."""
    known = {h: d for h, d in directions.items() if d in _DIRECTION_SIGN}
    if len(known) < 2:
        return None

    short_term = _group_direction_label(known, _HORIZON_GROUPS["short_term"])
    medium_term = _group_direction_label(known, _HORIZON_GROUPS["medium_term"])
    long_term = _group_direction_label(known, _HORIZON_GROUPS["long_term"])

    items = list(known.items())
    agreeing_pairs = 0
    total_pairs = 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            total_pairs += 1
            if _DIRECTION_SIGN[items[i][1]] == _DIRECTION_SIGN[items[j][1]]:
                agreeing_pairs += 1
    consistency_pct = round(100 * agreeing_pairs / total_pairs, 1) if total_pairs else None

    parts = []
    if short_term is not None:
        parts.append(f"Short-term (24h): {short_term}")
    if medium_term is not None:
        parts.append(f"Medium-term (3d-7d): {medium_term}")
    if long_term is not None:
        parts.append(f"Long-term (30d): {long_term}")
    if total_pairs:
        parts.append(
            f"{agreeing_pairs}/{total_pairs} horizon pairs agree ({consistency_pct}% consistency)"
        )
    explanation = ". ".join(parts) + "." if parts else ""

    return {
        "short_term": short_term,
        "medium_term": medium_term,
        "long_term": long_term,
        "consistency_pct": consistency_pct,
        "agreeing_pairs": agreeing_pairs,
        "total_pairs": total_pairs,
        "horizons_available": sorted(known),
        "explanation": explanation,
    }


def check_target_reached(
    direction: str, current_price: float, target_price: float, window_rows: list
) -> bool | None:
    """Pure function: Forecast Intelligence Upgrade -- did price actually
    TOUCH target_price at any point during the window between the
    forecast and its grading, not just where it happened to end up at
    horizon-elapse (which is all error_pct/direction_correct check)?
    Walks `window_rows`' (ascending, the bars strictly after the
    forecast's own reference bar through the elapsed bar) real intrabar
    high/low -- the same real-range read `simulate_trade_outcome`
    (app.services.trade_setup.engine) uses for trade setups, but this
    checks a single level, not two: a directional forecast's target has
    no accompanying stop to race against, so there's nothing to resolve
    an ambiguous same-bar touch against.

    None for a Neutral call or when target_price doesn't actually differ
    from current_price -- there's no directional touch to check."""
    if _DIRECTION_SIGN.get(direction, 0) == 0:
        return None
    if target_price == current_price:
        return None
    if target_price > current_price:
        return any(float(row.high) >= target_price for row in window_rows)
    return any(float(row.low) <= target_price for row in window_rows)


def compute_excursions(
    direction: str, current_price: float, window_rows: list
) -> tuple[float | None, float | None]:
    """Pure function: Forecasting 2.0 (Part 20/21) -- path analysis, not
    just the final-price error_pct: the best (MFE) and worst (MAE)
    percentage excursion from current_price during the same window
    check_target_reached already walks (real intrabar high/low, zero extra
    I/O). Signed relative to `direction`, matching the exact convention
    AlertPerformanceGrade's own max_favorable/adverse_excursion_pct already
    use elsewhere in this codebase: for a Bullish call, MFE is the highest
    % gain reached (positive) and MAE is the deepest % drawdown (negative);
    for Bearish these invert (MFE negative -- price fell, as the call
    implied -- MAE positive). Both None for a Neutral call or an empty
    window -- there is no "favorable side" to measure."""
    if _DIRECTION_SIGN.get(direction, 0) == 0 or not window_rows:
        return None, None
    max_up_pct = 100 * (max(float(r.high) for r in window_rows) - current_price) / current_price
    max_down_pct = 100 * (min(float(r.low) for r in window_rows) - current_price) / current_price
    if _DIRECTION_SIGN[direction] > 0:
        return round(max_up_pct, 4), round(max_down_pct, 4)
    return round(max_down_pct, 4), round(max_up_pct, 4)


def classify_error_type(
    direction_correct: bool | None,
    target_reached: bool | None,
    confidence_correct: bool | None,
) -> str | None:
    """Pure function: Forecasting 2.0 (Part 27) -- a coarse, honestly-
    derivable classification of what kind of miss this was, using only
    fields this same grading pass already computed. None for a correct or
    ungradable-direction (Neutral) call -- there is nothing to classify.
    Deliberately limited to what these three fields can actually
    distinguish -- see PriceForecastSnapshot.error_type's own docstring for
    why the full spec taxonomy (regime/event/model attribution, which would
    need causal evidence this row doesn't have) isn't attempted here."""
    if direction_correct is not False:
        return None
    if target_reached is True:
        return "TIMING_ERROR"  # right call, price touched target, but reversed by horizon-elapse
    if confidence_correct is False:
        return "VOLATILITY_ERROR"  # missed by more than this call's own expected volatility band
    return "DIRECTION_ERROR"


def summarize_official_performance(
    graded: list[tuple[bool, float | None, bool | None]],
) -> dict:
    """Pure function: Forecasting 2.0 (Page 4, Performance) -- the four-
    number executive summary over every graded official daily forecast
    (any symbol, any regime, whatever direction it called): how many
    forecasts have resolved, overall direction accuracy, average
    |error_pct|, and the target-reached rate. `graded` is
    (direction_correct, error_pct, target_reached) triples already
    filtered upstream to rows with a resolvable direction_correct (a
    Neutral call is excluded before this function sees it, same as
    aggregate_agent_performance). error_pct/target_reached are each
    averaged only over the rows that actually have one -- a Neutral call
    has no target_reached verdict, so it's excluded from that rate
    rather than silently counted as a miss."""
    if not graded:
        return {
            "graded_count": 0,
            "direction_accuracy_pct": None,
            "avg_abs_error_pct": None,
            "target_reached_rate_pct": None,
        }
    correct_flags = [correct for correct, _, _ in graded]
    errors = [abs(error) for _, error, _ in graded if error is not None]
    reached_flags = [reached for _, _, reached in graded if reached is not None]
    return {
        "graded_count": len(graded),
        "direction_accuracy_pct": round(100 * sum(correct_flags) / len(correct_flags), 2),
        "avg_abs_error_pct": round(sum(errors) / len(errors), 2) if errors else None,
        "target_reached_rate_pct": (
            round(100 * sum(reached_flags) / len(reached_flags), 2) if reached_flags else None
        ),
    }


def derive_official_calibration_curve(
    graded: list[tuple[int, bool]],
    bin_width: int = 20,
) -> list[dict]:
    """Pure function: Forecasting 2.0 (Page 4, Performance) -- buckets
    official daily forecasts by their own stated probability_pct and
    compares each bucket's average stated probability to its observed
    direction_correct rate. `graded` is (probability_pct, direction_correct)
    pairs, already filtered upstream to graded rows.

    Deliberately a thin sibling of quality.metrics.compute_calibration
    rather than a forced reuse: that function's bucketing expects the
    older Probability Engine's three-way (prob_up/down/flat_pct) shape,
    but an official forecast only ever persists one probability for
    whichever single direction it called. `classify_calibration_reliability`
    IS imported and reused as-is (not reimplemented) for the sample-
    sufficiency label, so a bucket here carries the same trust semantics
    (and the same insufficient/usable/reliable thresholds) as every other
    calibration bucket already shown elsewhere in the app."""
    buckets: dict[int, list[tuple[int, bool]]] = defaultdict(list)
    for probability_pct, correct in graded:
        bin_start = min(int(probability_pct // bin_width) * bin_width, 100 - bin_width)
        buckets[bin_start].append((probability_pct, correct))

    result = []
    for bin_start in sorted(buckets):
        entries = buckets[bin_start]
        count = len(entries)
        avg_probability = round(sum(p for p, _ in entries) / count, 2)
        observed_accuracy = round(100 * sum(1 for _, c in entries if c) / count, 2)
        result.append(
            {
                "probability_bucket": f"{bin_start}-{bin_start + bin_width}%",
                "count": count,
                "avg_stated_probability_pct": avg_probability,
                "observed_accuracy_pct": observed_accuracy,
                "calibration_gap_pct": round(avg_probability - observed_accuracy, 2),
                "sample_sufficiency": classify_calibration_reliability(count),
            }
        )
    return result


def derive_regime_performance_breakdown(
    graded: list[tuple[str, bool]], min_sample_size: int
) -> list[dict]:
    """Pure function: Forecasting 2.0 (Page 4, Performance) -- direction
    accuracy grouped by regime_at_forecast ALONE, not per-agent (see
    Agent Performance/Learning Center for that finer grouping). `graded`
    is (regime, direction_correct) pairs, already filtered upstream to
    graded rows with a known regime. Reuses the exact same statistical-
    honesty gate as aggregate_agent_performance (a group below
    min_sample_size reports accuracy_pct=None and insufficient_sample=True
    rather than an unreliable percentage) -- same rule, coarser grouping
    key, so this stays a separate small function rather than a forced
    generalization of aggregate_agent_performance's tuple-keyed buckets."""
    buckets: dict[str, list[bool]] = defaultdict(list)
    for regime, correct in graded:
        buckets[regime].append(correct)

    results = []
    for regime in sorted(buckets):
        outcomes = buckets[regime]
        sample_size = len(outcomes)
        insufficient = sample_size < min_sample_size
        results.append(
            {
                "regime": regime,
                "sample_size": sample_size,
                "accuracy_pct": None
                if insufficient
                else round(100 * sum(outcomes) / sample_size, 1),
                "insufficient_sample": insufficient,
            }
        )
    return results


def aggregate_agent_performance(
    graded: list[tuple[str, str, bool]], min_sample_size: int
) -> list[dict]:
    """Pure function: Forecasting 2.0 (Part 26) -- per (agent, symbol)
    direction accuracy, conditioned on the agent actually having
    participated (a real confidence_pct, not missing/unavailable data) in
    graded official daily forecasts. `graded` is (agent_name, symbol,
    direction_correct) triples, already filtered upstream to rows where
    the agent had real data and the parent forecast graded a resolvable
    direction (a Neutral call has direction_correct=None and is excluded
    before this function ever sees it).

    Every AgentForecast row mirrors its parent forecast's own direction
    (see AgentForecast's own docstring -- there is no independent per-
    agent direction call in this data model), so this reports realized
    accuracy on the subset of graded days each agent actually had data
    for, not a claim that the agent alone drove the outcome. Groups with
    fewer than `min_sample_size` observations report accuracy_pct=None
    and insufficient_sample=True rather than an unreliable percentage
    from a handful of forecasts -- same statistical-honesty rule this
    project's calibration engine already applies."""
    buckets: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for agent_name, symbol, correct in graded:
        buckets[(agent_name, symbol)].append(correct)

    results = []
    for (agent_name, symbol), outcomes in sorted(buckets.items()):
        sample_size = len(outcomes)
        insufficient = sample_size < min_sample_size
        results.append(
            {
                "agent_name": agent_name,
                "symbol": symbol,
                "sample_size": sample_size,
                "accuracy_pct": None
                if insufficient
                else round(100 * sum(outcomes) / sample_size, 1),
                "insufficient_sample": insufficient,
            }
        )
    return results


def derive_learning_insights(
    graded: list[tuple[str, str, str, bool]],
    min_sample_size: int,
    min_gap_pct: float,
) -> list[dict]:
    """Pure function: Forecasting 2.0 (Part 33 / Page 7, Learning Center)
    -- the one honest, non-fabricated "what the system learned" signal
    this data model can actually support: for a given (agent, symbol),
    does its realized direction accuracy differ meaningfully between two
    market regimes it's actually been graded in? `graded` is (agent_name,
    symbol, regime_at_forecast, direction_correct) quadruples, same
    upstream filtering as aggregate_agent_performance (agent had real
    data, parent forecast graded a resolvable direction) plus a non-null
    regime.

    An insight is only ever emitted when BOTH regime buckets independently
    clear `min_sample_size` (a comparison built on a 2-observation bucket
    proves nothing) AND the accuracy gap between them is at least
    `min_gap_pct` (two buckets a couple points apart are statistically
    indistinguishable noise, not a real regime effect) -- this project's
    same statistical-honesty rule as calibration/agent-performance,
    applied here to a comparison instead of a single number. Symbols/
    agents with fewer than two qualifying regimes produce no insight at
    all rather than a guessed one. `statement` is a plain description of
    the two observed rates, deliberately phrased as correlational
    ("was right more often in X than Y"), never causal ("X works
    because...") -- this data has no causal evidence to support that."""
    buckets: dict[tuple[str, str, str], list[bool]] = defaultdict(list)
    for agent_name, symbol, regime, correct in graded:
        buckets[(agent_name, symbol, regime)].append(correct)

    by_agent_symbol: dict[tuple[str, str], dict[str, list[bool]]] = defaultdict(dict)
    for (agent_name, symbol, regime), outcomes in buckets.items():
        by_agent_symbol[(agent_name, symbol)][regime] = outcomes

    insights = []
    for (agent_name, symbol), regimes in sorted(by_agent_symbol.items()):
        qualifying = {
            regime: outcomes
            for regime, outcomes in regimes.items()
            if len(outcomes) >= min_sample_size
        }
        if len(qualifying) < 2:
            continue
        accuracy_by_regime = {
            regime: 100 * sum(outcomes) / len(outcomes) for regime, outcomes in qualifying.items()
        }
        better_regime = max(accuracy_by_regime, key=accuracy_by_regime.get)
        worse_regime = min(accuracy_by_regime, key=accuracy_by_regime.get)
        gap = accuracy_by_regime[better_regime] - accuracy_by_regime[worse_regime]
        if gap < min_gap_pct:
            continue
        better_acc = round(accuracy_by_regime[better_regime], 1)
        worse_acc = round(accuracy_by_regime[worse_regime], 1)
        insights.append(
            {
                "agent_name": agent_name,
                "symbol": symbol,
                "better_regime": better_regime,
                "better_accuracy_pct": better_acc,
                "better_sample_size": len(qualifying[better_regime]),
                "worse_regime": worse_regime,
                "worse_accuracy_pct": worse_acc,
                "worse_sample_size": len(qualifying[worse_regime]),
                "statement": (
                    f"{agent_name} was right more often in {better_regime} "
                    f"({better_acc}%, n={len(qualifying[better_regime])}) than in "
                    f"{worse_regime} ({worse_acc}%, n={len(qualifying[worse_regime])})."
                ),
            }
        )
    return insights


def _realized_sign(current_price: float, realized_price: float) -> int:
    if realized_price > current_price:
        return 1
    if realized_price < current_price:
        return -1
    return 0


def grade_direction(direction: str, current_price: float, realized_price: float) -> bool | None:
    """Pure function: did this forecast's own directional call match the
    real sign of price change from `current_price` (the reference row's
    close) to `realized_price`? Honestly `None` for a "Neutral" call --
    a neutral read makes no directional claim, so there's nothing to
    grade right or wrong."""
    predicted_sign = _DIRECTION_SIGN.get(direction)
    if not predicted_sign:
        return None
    return predicted_sign == _realized_sign(current_price, realized_price)


def grade_momentum_baseline(
    prior_return_pct: float | None, current_price: float, realized_price: float
) -> bool | None:
    """Pure function: POST-V9 Phase 14 -- would the naive "yesterday's
    move continues" baseline have called this forecast's own realized
    outcome correctly? Uses the exact same realized-sign criterion
    grade_direction applies to the real forecast, so the two accuracy
    rates are directly comparable in aggregate (see
    app.services.accuracy.engine._aggregate_stats). None when there's no
    prior period to read a direction from, or when the prior period was
    itself exactly flat -- like a Neutral forecast call, a flat baseline
    makes no directional claim to grade."""
    if not prior_return_pct:
        return None
    predicted_sign = 1 if prior_return_pct > 0 else -1
    return predicted_sign == _realized_sign(current_price, realized_price)


def compute_historical_mean_baseline_error_pct(
    historical_mean_baseline_return_pct: float | None,
    current_price: float,
    realized_price: float,
) -> float | None:
    """Pure function: POST-V9 Phase 14 -- the price-target error a naive
    "assume the future equals this symbol's own historical average
    forward return" baseline would have made, computed the exact same way
    `error_pct` is computed for the real forecast (both are
    100*(realized-target)/target), so the two are directly comparable
    magnitude-for-magnitude. None when there's no historical baseline
    return to build a naive target from."""
    if historical_mean_baseline_return_pct is None:
        return None
    naive_target_price = current_price * (1 + historical_mean_baseline_return_pct / 100)
    if naive_target_price == 0:
        return None
    return round(100 * (realized_price - naive_target_price) / naive_target_price, 4)


def grade_confidence(error_pct: float, expected_volatility_pct: float | None) -> bool | None:
    """Pure function: did the real error stay within this forecast's own
    ATR-derived expected volatility band -- the same "no better than
    noise" baseline `price_forecast_quality_multiplier` already uses?
    None (not fabricated) when no real volatility band exists for this
    row."""
    if expected_volatility_pct is None or expected_volatility_pct <= 0:
        return None
    return abs(error_pct) <= expected_volatility_pct


async def grade_price_forecasts(
    session_factory: async_sessionmaker[AsyncSession], symbol: str, model: type
) -> int:
    """Fills in `realized_price`/`error_pct`/`direction_correct`/
    `confidence_correct`/`evaluated_at` on every ungraded
    `PriceForecastSnapshot` row whose horizon has actually elapsed in
    stored history -- mirrors
    app.services.learning.engine.evaluate_predictions()'s index-by-
    timestamp join exactly (same reasoning: a forecast only becomes
    gradable once real history reaches that far, never guessed). POST-V9
    Phase 17: also transitions `forecast_status` via status_after_grading
    -- a still-ACTIVE row becomes GRADED, while one that was already
    INVALIDATED/SUPERSEDED before its horizon elapsed keeps that status
    (grading never erases an existing lifecycle marker). POST-V9 Phase 14:
    also fills in `momentum_baseline_correct`/
    `historical_mean_baseline_error_pct` -- two naive-baseline comparisons
    computed entirely from the same `rows` already fetched for grading, no
    extra I/O -- so app.services.accuracy.engine can report whether the
    forecast actually beats doing nothing clever. Forecasting 2.0 (Part
    20/21/27): also fills in `max_favorable_excursion_pct`/
    `max_adverse_excursion_pct` (path analysis, not just the final-price
    error) and `error_type` (a coarse, honestly-derivable classification of
    wrong calls) -- both computed from the exact same already-fetched
    grading window, still zero extra I/O. Returns how many rows were
    graded this call."""
    async with session_factory() as session:
        ungraded = list(
            await session.scalars(
                select(PriceForecastSnapshot).where(
                    PriceForecastSnapshot.symbol == symbol,
                    PriceForecastSnapshot.reference_timestamp.is_not(None),
                    PriceForecastSnapshot.evaluated_at.is_(None),
                )
            )
        )
    if not ungraded:
        return 0

    rows = await get_series(session_factory, model, symbol, Timeframe.DAILY)
    index_by_timestamp = {r.timestamp: i for i, r in enumerate(rows)}
    returns_series = [float(r.return_pct) if r.return_pct is not None else None for r in rows]

    graded = 0
    async with session_factory() as session:
        for snapshot in ungraded:
            idx = index_by_timestamp.get(snapshot.reference_timestamp)
            if idx is None:
                continue
            horizon_periods = HORIZONS.get(snapshot.horizon)
            if horizon_periods is None:
                continue
            target_idx = idx + horizon_periods
            if target_idx >= len(rows):
                continue  # horizon hasn't elapsed in stored history yet

            realized_price = float(rows[target_idx].close)
            target_price = float(snapshot.target_price)
            if target_price == 0:
                continue
            error_pct = 100 * (realized_price - target_price) / target_price

            current_price = float(snapshot.current_price)
            reference_atr = rows[idx].atr
            expected_volatility_pct = (
                round(float(reference_atr) / current_price * 100, 4)
                if reference_atr is not None and current_price
                else None
            )

            prior_return_pct = returns_series[idx - 1] if idx > 0 else None
            historical_mean_baseline_return_pct = compute_baseline_return_pct(
                returns_series, idx, horizon_periods
            )

            db_row = await session.get(PriceForecastSnapshot, snapshot.id)
            db_row.realized_price = realized_price
            db_row.error_pct = round(error_pct, 4)
            db_row.direction_correct = grade_direction(
                snapshot.direction, current_price, realized_price
            )
            db_row.confidence_correct = grade_confidence(error_pct, expected_volatility_pct)
            grading_window = rows[idx + 1 : target_idx + 1]
            db_row.target_reached = check_target_reached(
                snapshot.direction, current_price, target_price, grading_window
            )
            mfe_pct, mae_pct = compute_excursions(snapshot.direction, current_price, grading_window)
            db_row.max_favorable_excursion_pct = mfe_pct
            db_row.max_adverse_excursion_pct = mae_pct
            db_row.error_type = classify_error_type(
                db_row.direction_correct, db_row.target_reached, db_row.confidence_correct
            )
            db_row.momentum_baseline_correct = grade_momentum_baseline(
                prior_return_pct, current_price, realized_price
            )
            db_row.historical_mean_baseline_error_pct = compute_historical_mean_baseline_error_pct(
                historical_mean_baseline_return_pct, current_price, realized_price
            )
            db_row.evaluated_at = datetime.now(UTC)
            db_row.forecast_status = status_after_grading(db_row.forecast_status)
            graded += 1
        await session.commit()
    return graded


async def check_and_invalidate_forecasts(
    session_factory: async_sessionmaker[AsyncSession], symbol: str, model: type
) -> int:
    """Re-evaluates every still-ACTIVE, not-yet-graded PriceForecastSnapshot
    for `symbol` against the latest known price and regime, marking any
    whose structured invalidation rules (app.services.forecast.
    invalidation) fire as INVALIDATED. Runs independently of
    grade_price_forecasts -- that only fires once a forecast's horizon has
    fully elapsed, while invalidation can and should fire earlier, the
    moment the forecast's own stated conditions no longer hold. Returns how
    many rows were invalidated this call."""
    async with session_factory() as session:
        active = list(
            await session.scalars(
                select(PriceForecastSnapshot).where(
                    PriceForecastSnapshot.symbol == symbol,
                    PriceForecastSnapshot.forecast_status == ForecastStatus.ACTIVE.value,
                    PriceForecastSnapshot.evaluated_at.is_(None),
                )
            )
        )
    if not active:
        return 0

    rows = await get_series(session_factory, model, symbol, Timeframe.DAILY)
    if not rows:
        return 0
    current_price = float(rows[-1].close)

    async with session_factory() as session:
        latest_regime_row = await session.scalar(
            select(MarketRegimeSnapshot).order_by(MarketRegimeSnapshot.computed_at.desc()).limit(1)
        )
    current_regime = latest_regime_row.regime.value if latest_regime_row is not None else None

    invalidated = 0
    async with session_factory() as session:
        for snapshot in active:
            invalidation_level = snapshot.key_levels.get("invalidation_level")
            result = evaluate_invalidation(
                snapshot.direction,
                float(invalidation_level) if invalidation_level is not None else None,
                current_price,
                snapshot.regime_at_forecast,
                current_regime,
            )
            if result["status"] != "INVALIDATED":
                continue
            db_row = await session.get(PriceForecastSnapshot, snapshot.id)
            db_row.forecast_status = ForecastStatus.INVALIDATED.value
            db_row.invalidation_reason = result["invalidation_reason"]
            db_row.invalidated_at = datetime.now(UTC)
            invalidated += 1
        await session.commit()
    return invalidated


async def summarize_forecast_accuracy(
    session_factory: async_sessionmaker[AsyncSession], symbol: str, horizon: str, limit: int = 50
) -> dict | None:
    """Real, measured accuracy over this symbol/horizon's own graded
    forecast history -- never a simulated number. None (not zero) when
    nothing has been graded yet."""
    async with session_factory() as session:
        graded = list(
            await session.scalars(
                select(PriceForecastSnapshot)
                .where(
                    PriceForecastSnapshot.symbol == symbol,
                    PriceForecastSnapshot.horizon == horizon,
                    PriceForecastSnapshot.evaluated_at.is_not(None),
                )
                .order_by(PriceForecastSnapshot.evaluated_at.desc())
                .limit(limit)
            )
        )
    if not graded:
        return None
    errors = [abs(float(g.error_pct)) for g in graded if g.error_pct is not None]
    if not errors:
        return None
    return {
        "evaluated_count": len(errors),
        "avg_abs_error_pct": round(sum(errors) / len(errors), 4),
    }


class ForecastEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        probability_engine: ProbabilityEngine,
        quality_engine: PredictionQualityEngine,
        technical_engine: TechnicalAnalysisEngine,
        explanation_engine: ExplanationEngine,
        economic_calendar_engine: EconomicCalendarEngine,
        sentiment_engine: SentimentEngine,
        correlation_engine: CorrelationEngine,
        whale_engine: WhaleIntelligenceEngine,
        onchain_engine: OnChainIntelligenceEngine,
        pattern_engine: PatternEngine,
    ) -> None:
        self._session_factory = session_factory
        self._probability_engine = probability_engine
        self._quality_engine = quality_engine
        self._technical_engine = technical_engine
        self._explanation_engine = explanation_engine
        self._economic_calendar_engine = economic_calendar_engine
        self._sentiment_engine = sentiment_engine
        self._correlation_engine = correlation_engine
        self._whale_engine = whale_engine
        self._onchain_engine = onchain_engine
        self._pattern_engine = pattern_engine

    async def _latest_watchdog_snapshot(
        self, as_of: datetime | None = None
    ) -> WatchdogSnapshot | None:
        """`as_of` (Data Leakage Protection, Phase 23) bounds this read to
        what was actually knowable at that timestamp -- same reasoning and
        same pattern as SentimentEngine.get_latest(as_of=...). Without
        this, a forecast computed for an older reference_timestamp (a
        re-graded or backfilled read) could silently pull in a regime/
        risk/macro reading a WatchdogSnapshot cycle only produced after
        the forecast's own reference bar."""
        query = select(WatchdogSnapshot)
        if as_of is not None:
            query = query.where(WatchdogSnapshot.computed_at <= as_of)
        query = query.order_by(WatchdogSnapshot.computed_at.desc()).limit(1)
        async with self._session_factory() as session:
            return await session.scalar(query)

    async def _confidence_breakdown(
        self,
        symbol: str,
        technical_confidence: float | None,
        watchdog: WatchdogSnapshot | None,
        momentum_score: float | None,
        as_of: datetime | None = None,
    ) -> list[ConfidenceRow]:
        # Forecasting 2.0 (Part 41): bounds the sentiment read to what was
        # actually knowable at this forecast's own reference bar -- without
        # this, a forecast computed "as of" an older reference_timestamp
        # (e.g. a re-graded or backfilled read) could silently absorb
        # sentiment published after the fact.
        sentiment_snapshot = await self._sentiment_engine.get_latest(as_of=as_of)
        correlations = await self._correlation_engine.get_latest(as_of=as_of)
        whale_snapshot = await self._whale_engine.get_snapshot(symbol)
        onchain_snapshot = await self._onchain_engine.get_snapshot(symbol)
        pattern_signals = await self._pattern_engine.get_latest(
            symbol, timeframe=Timeframe.DAILY, limit=10
        )
        _, pattern_confidence_raw = _recency_weighted_direction(pattern_signals)
        pattern_confidence = (
            round(pattern_confidence_raw) if pattern_confidence_raw is not None else None
        )

        rows = [
            ConfidenceRow(
                "Technical Analysis",
                round(technical_confidence) if technical_confidence is not None else None,
            ),
            ConfidenceRow(
                "News",
                _distance_from_neutral(
                    sentiment_snapshot.news_sentiment_score if sentiment_snapshot else None
                ),
            ),
            ConfidenceRow(
                "Sentiment",
                _distance_from_neutral(
                    sentiment_snapshot.global_sentiment_score if sentiment_snapshot else None
                ),
            ),
            ConfidenceRow(
                "Macro",
                round(watchdog.confidence_score)
                if watchdog is not None and watchdog.confidence_score is not None
                else None,
            ),
            ConfidenceRow("Whales", _whale_confidence(whale_snapshot)),
            ConfidenceRow("On-chain", _onchain_confidence(onchain_snapshot)),
            ConfidenceRow("Correlations", _correlation_confidence(correlations, symbol)),
            # Momentum reuses the exact same 0-100 score already shown on the
            # forecast payload's own `momentum_score` field -- distance from
            # its 50 (neutral) center is a real confidence proxy, the same
            # transform `_distance_from_neutral` already applies to News/
            # Sentiment's own centered scores.
            ConfidenceRow("Momentum", _distance_from_neutral(momentum_score)),
            ConfidenceRow("Pattern", pattern_confidence),
            # Risk reuses GlobalScoreEngine's own risk_score, already copied
            # onto WatchdogSnapshot each cycle -- distance from its 50
            # (neutral) center, same transform as Momentum/News/Sentiment.
            ConfidenceRow(
                "Risk",
                _distance_from_neutral(
                    float(watchdog.risk_score)
                    if watchdog is not None and watchdog.risk_score is not None
                    else None
                ),
            ),
        ]
        return rows

    async def _what_can_change(self, watchdog: WatchdogSnapshot | None, symbol: str) -> list[str]:
        items: list[str] = []
        now = datetime.now(UTC)
        events: list[EconomicCalendarEvent] = await self._economic_calendar_engine.get_upcoming(
            days_ahead=14
        )
        for event in events[:3]:
            days = max(0, (event.event_date - now).days)
            when = "today" if days == 0 else f"in {days} day{'s' if days != 1 else ''}"
            items.append(f"{event.title} {when}")

        if watchdog is not None and watchdog.consensus:
            invalidation = watchdog.consensus.get("invalidation_risk")
            if invalidation:
                items.append(invalidation)

        return items

    async def compute(
        self, symbol: str, horizon_label: str = "24h", is_official_daily: bool = False
    ) -> dict | None:
        """`is_official_daily=True` (Forecasting 2.0, Part 2/3/4) is the
        one published record of the day for this symbol/horizon --
        `_persist()` enforces at most one such row per (symbol, horizon,
        UTC calendar date) via the DB's own partial unique index, so a
        duplicate call (e.g. a retried scheduler tick) is a graceful
        no-op that returns the existing official row's payload rather
        than a second row or a crash. Every other call site (the existing
        intraday recompute, the live dashboard fetch) keeps calling this
        with the default False, unaffected."""
        horizon_periods = HORIZONS.get(horizon_label)
        if horizon_periods is None:
            return None

        config = find_symbol_config(symbol)
        if config is None:
            return None

        # Built once per compute() call (one horizon) and handed to
        # ProbabilityEngine so its RSI-bucketed sample can also be filtered
        # to periods sharing today's market regime -- see
        # ProbabilityEngine.compute_and_store's own docstring for why this
        # is caller-provided rather than rebuilt internally.
        regime_index = await build_regime_index(self._session_factory, Timeframe.DAILY)
        probability_snapshot = await self._probability_engine.compute_and_store(
            config.symbol,
            config.model,
            Timeframe.DAILY,
            horizon=horizon_periods,
            regime_index=regime_index,
        )
        if probability_snapshot is None:
            return None

        # Fetched AFTER compute_and_store (not before) and pinned to the exact
        # bar its own internal fetch used (reference_timestamp), rather than
        # trusting a separately-fetched "latest" row -- two independent
        # get_series() calls racing against a concurrent history-sync commit
        # could otherwise return current_price/atr from a different bar than
        # the one the probability was actually computed from.
        rows = await get_series(self._session_factory, config.model, config.symbol, Timeframe.DAILY)
        if not rows:
            return None
        latest = next(
            (r for r in reversed(rows) if r.timestamp == probability_snapshot.reference_timestamp),
            rows[-1],
        )
        current_price = float(latest.close)
        atr = float(latest.atr) if latest.atr is not None else None

        quality = await self._quality_engine.evaluate(config.symbol, config.model, Timeframe.DAILY)
        confidence_pct = max(
            probability_snapshot.prob_up_pct,
            probability_snapshot.prob_down_pct,
            probability_snapshot.prob_flat_pct,
        )
        # POST-V9 Phase 12: reuses the exact `rows` already fetched above --
        # no second query -- to score how fresh this symbol's own synced
        # history actually is, so a read built on stale data doesn't reach
        # `effective_confidence_pct` at full strength. `assess_symbol_quality`
        # is DataQualityEngine's own pure function; this is the only place
        # in the codebase (besides its own /api/data-quality sweep) that
        # reads it -- previously it fed no decision path at all.
        data_quality = assess_symbol_quality(rows, datetime.now(UTC))
        data_quality_score = compute_data_quality_score(
            data_quality["days_since_last_update"], data_quality["status"]
        )
        conviction = classify_conviction(
            confidence_pct,
            sample_size=probability_snapshot.sample_size,
            brier_score=quality["brier_score"] if quality else None,
            evaluated_predictions=quality["evaluated_predictions"] if quality else None,
            data_quality_score=data_quality_score,
        )

        avg_forward_return_pct = float(probability_snapshot.avg_forward_return_pct)
        target_price = compute_price_target(current_price, avg_forward_return_pct)
        path = compute_price_path(current_price, avg_forward_return_pct)
        distribution = compute_probability_distribution(current_price, avg_forward_return_pct, atr)
        prediction_range = compute_prediction_range(current_price, avg_forward_return_pct, atr)
        scenario_cases = compute_scenario_cases(
            current_price,
            avg_forward_return_pct,
            atr,
            probability_snapshot.prob_up_pct,
            probability_snapshot.prob_down_pct,
            probability_snapshot.prob_flat_pct,
            conviction["effective_confidence_pct"],
        )
        expected_max_drawdown_pct = compute_expected_max_drawdown_pct(
            [float(r.return_pct) if r.return_pct is not None else None for r in rows]
        )
        direction_label = classify_direction_label(
            probability_snapshot.prob_up_pct, probability_snapshot.prob_down_pct
        )

        technical_snapshot = await self._technical_engine.get_latest(config.symbol)
        momentum_score = compute_momentum_score(
            float(technical_snapshot.momentum)
            if technical_snapshot is not None and technical_snapshot.momentum is not None
            else None
        )
        watchdog = await self._latest_watchdog_snapshot(latest.timestamp)
        explanation = await self._explanation_engine.build(config.symbol)
        confidence_breakdown = await self._confidence_breakdown(
            config.symbol,
            float(technical_snapshot.confidence)
            if technical_snapshot is not None and technical_snapshot.confidence is not None
            else None,
            watchdog,
            momentum_score,
            latest.timestamp,
        )
        what_can_change = await self._what_can_change(watchdog, config.symbol)

        regime = MarketRegime(watchdog.regime) if watchdog is not None and watchdog.regime else None
        regime_label = derive_regime_label(
            regime,
            float(watchdog.volatility)
            if watchdog is not None and watchdog.volatility is not None
            else None,
            float(technical_snapshot.trend_strength)
            if technical_snapshot is not None and technical_snapshot.trend_strength is not None
            else None,
        )
        risk_meter = derive_risk_meter(
            watchdog.risk_score if watchdog is not None else None, regime
        )

        support = (
            float(technical_snapshot.support)
            if technical_snapshot is not None and technical_snapshot.support is not None
            else None
        )
        resistance = (
            float(technical_snapshot.resistance)
            if technical_snapshot is not None and technical_snapshot.resistance is not None
            else None
        )
        key_levels = {
            "support_1": support,
            "support_2": (support - atr) if support is not None and atr is not None else None,
            "resistance_1": resistance,
            "resistance_2": (resistance + atr)
            if resistance is not None and atr is not None
            else None,
            "invalidation_level": support
            if direction_label in ("Bullish", "Strong Bullish")
            else resistance,
            "breakout_level": resistance
            if direction_label in ("Bullish", "Strong Bullish")
            else support,
        }

        consensus = watchdog.consensus if watchdog is not None else None

        expected_volatility_pct = (
            round(atr / current_price * 100, 2) if atr is not None and current_price else None
        )

        # Self-learning: how accurate has THIS symbol/horizon's own price
        # target actually been historically? Deliberately kept separate from
        # `confidence` above (which measures direction calibration) --
        # honestly None until enough forecasts have actually been graded.
        accuracy = await summarize_forecast_accuracy(
            self._session_factory, config.symbol, horizon_label
        )
        track_record_multiplier = price_forecast_quality_multiplier(
            accuracy["avg_abs_error_pct"] if accuracy else None,
            accuracy["evaluated_count"] if accuracy else None,
            expected_volatility_pct,
        )
        track_record = {
            "evaluated_count": accuracy["evaluated_count"] if accuracy else 0,
            "avg_abs_error_pct": accuracy["avg_abs_error_pct"] if accuracy else None,
            "quality_multiplier": track_record_multiplier,
            "adjusted_confidence_pct": (
                round(conviction["effective_confidence_pct"] * track_record_multiplier)
                if track_record_multiplier is not None
                else None
            ),
        }

        payload = {
            "symbol": config.symbol,
            "horizon": horizon_label,
            "computed_at": datetime.now(UTC).isoformat(),
            "reference_timestamp": latest.timestamp.isoformat(),
            "current_price": current_price,
            "target_price": round(target_price, 8),
            "expected_change_pct": round(avg_forward_return_pct, 4),
            "direction": direction_label,
            "probability_pct": confidence_pct,
            "confidence": conviction,
            "track_record": track_record,
            "expected_range": {
                "low": round(current_price - atr, 8) if atr is not None else None,
                "high": round(current_price + atr, 8) if atr is not None else None,
            },
            "expected_volatility_pct": expected_volatility_pct,
            "expected_max_drawdown_pct": expected_max_drawdown_pct,
            "trend_strength": float(technical_snapshot.trend_strength)
            if technical_snapshot is not None and technical_snapshot.trend_strength is not None
            else None,
            "momentum_score": momentum_score,
            "price_path": path,
            "probability_distribution": distribution,
            "prediction_range": prediction_range,
            "scenario_cases": scenario_cases,
            "reasons": explanation.get("indicators", []),
            "confidence_breakdown": [
                {"name": r.name, "confidence_pct": r.confidence_pct} for r in confidence_breakdown
            ],
            "consensus": consensus,
            "regime": regime_label,
            "risk_meter": risk_meter,
            "key_levels": key_levels,
            "what_can_change": what_can_change,
            "sample_size": probability_snapshot.sample_size,
            # The empirical spread behind expected_change_pct's single mean,
            # and whether the sample was actually regime-conditioned (see
            # ProbabilityEngine.compute_and_store / compute_rsi_probability).
            # getattr-guarded: older/mocked snapshots predating these
            # columns are treated as honestly unavailable, not a crash.
            "forward_return_quantiles": {
                key: (float(value) if value is not None else None)
                for key, value in (
                    (name, getattr(probability_snapshot, name, None))
                    for name in ("p10_pct", "p25_pct", "p50_pct", "p75_pct", "p90_pct")
                )
            },
            "regime_conditioned": getattr(probability_snapshot, "regime_conditioned", False),
            "reference_regime": getattr(probability_snapshot, "reference_regime", None),
            # POST-V9 Phase 8 (F-3): the same Prediction Quality Lab
            # calibration buckets `quality_multiplier` above was already
            # derived from, exposed in full so a consumer (NO_TRADE) can
            # find the bucket matching THIS forecast's own confidence level
            # and read its real calibration_gap_pct -- not a new
            # computation, the exact same `quality["calibration"]` this
            # engine already computed for the conviction discount.
            "calibration": quality["calibration"] if quality else None,
            # POST-V9 Phase 12: the same data_quality_score classify_conviction
            # above already discounted effective_confidence_pct by, exposed
            # so a consumer can see WHY confidence was reduced, not just that
            # it was.
            "data_quality": {
                "status": data_quality["status"],
                "days_since_last_update": data_quality["days_since_last_update"],
                "data_quality_score": data_quality_score,
            },
        }

        regime_at_forecast = regime.value if regime is not None else None
        forecast_version = await self._persist(
            payload,
            latest.timestamp,
            conviction["tier"],
            regime_at_forecast,
            is_official_daily,
            confidence_breakdown,
        )
        payload["forecast_version"] = forecast_version
        payload["forecast_status"] = ForecastStatus.ACTIVE.value
        return payload

    async def _persist(
        self,
        payload: dict,
        reference_timestamp: datetime,
        confidence_tier: str,
        regime_at_forecast: str | None,
        is_official_daily: bool,
        confidence_breakdown: list[ConfidenceRow],
    ) -> int:
        """Always INSERTs a new row (this table is append-only by design --
        an existing forecast is never overwritten). `forecast_version` is
        the Nth forecast computed for this exact (symbol, horizon) pair,
        making that lineage explicit rather than implicit in insertion
        order. POST-V9 Phase 17: also supersedes any prior row for this
        same (symbol, horizon) that's still ACTIVE (status_after_superseded
        -- their own predicted values are untouched, only the lifecycle
        marker changes), so at most one ACTIVE forecast ever exists per
        (symbol, horizon) at a time. Returns the version number assigned.

        Forecasting 2.0 (Part 2/4): when `is_official_daily`, checks first
        whether today's (symbol, horizon) official row already exists --
        the DB's own partial unique index (uq_official_daily_forecast) is
        the real guarantee, this check just makes a retried/duplicate
        scheduler tick a graceful no-op (return the existing version)
        instead of an IntegrityError. Forecasting 2.0 (Part 10/11): every
        persisted forecast (official or not) also gets one AgentForecast
        row per confidence_breakdown entry -- the per-agent evidence table
        the spec asks for, built from data ForecastEngine already computed
        this cycle, not a new agent system."""
        today = datetime.now(UTC).date()
        async with self._session_factory() as session:
            if is_official_daily:
                existing = await session.scalar(
                    select(PriceForecastSnapshot).where(
                        PriceForecastSnapshot.symbol == payload["symbol"],
                        PriceForecastSnapshot.horizon == payload["horizon"],
                        PriceForecastSnapshot.is_official_daily.is_(True),
                        PriceForecastSnapshot.official_forecast_date == today,
                    )
                )
                if existing is not None:
                    return existing.forecast_version

            prior_version = await session.scalar(
                select(func.max(PriceForecastSnapshot.forecast_version)).where(
                    PriceForecastSnapshot.symbol == payload["symbol"],
                    PriceForecastSnapshot.horizon == payload["horizon"],
                )
            )
            next_version = (prior_version or 0) + 1

            prior_active = list(
                await session.scalars(
                    select(PriceForecastSnapshot).where(
                        PriceForecastSnapshot.symbol == payload["symbol"],
                        PriceForecastSnapshot.horizon == payload["horizon"],
                        PriceForecastSnapshot.forecast_status == ForecastStatus.ACTIVE.value,
                    )
                )
            )
            for row in prior_active:
                row.forecast_status = status_after_superseded(row.forecast_status)

            row = PriceForecastSnapshot(
                symbol=payload["symbol"],
                horizon=payload["horizon"],
                current_price=payload["current_price"],
                target_price=payload["target_price"],
                expected_change_pct=payload["expected_change_pct"],
                direction=payload["direction"],
                probability_pct=payload["probability_pct"],
                confidence_tier=confidence_tier,
                checkpoints=payload["price_path"],
                distribution=payload["probability_distribution"],
                key_levels=payload["key_levels"],
                reference_timestamp=reference_timestamp,
                forecast_version=next_version,
                model_version=FORECAST_MODEL_VERSION,
                regime_at_forecast=regime_at_forecast,
                is_official_daily=is_official_daily,
                official_forecast_date=today if is_official_daily else None,
            )
            session.add(row)
            await session.flush()  # assigns row.id, needed for AgentForecast FKs below

            for source in confidence_breakdown:
                session.add(
                    AgentForecast(
                        forecast_id=row.id,
                        agent_name=source.name,
                        direction=payload["direction"],
                        confidence_pct=source.confidence_pct,
                        key_factors=[],
                        computed_at=datetime.now(UTC),
                    )
                )

            await session.commit()
        return next_version

    async def get_latest_history(self, symbol: str, limit: int = 20) -> list[PriceForecastSnapshot]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(PriceForecastSnapshot)
                .where(PriceForecastSnapshot.symbol == symbol.upper())
                .order_by(PriceForecastSnapshot.computed_at.desc())
                .limit(limit)
            )
            return list(result)

    async def get_latest_per_horizon(self, symbol: str) -> dict[str, PriceForecastSnapshot]:
        """Forecast Intelligence Upgrade: one row per horizon, the most
        recently computed. `.limit(200)` is a generous safety bound, not a
        tuning knob -- with only 4 horizons the first occurrence of each is
        always found within the first few rows of this already-indexed,
        already-descending scan (same query shape `get_latest_history`
        already uses), so this adds no new query pattern."""
        async with self._session_factory() as session:
            result = await session.scalars(
                select(PriceForecastSnapshot)
                .where(PriceForecastSnapshot.symbol == symbol.upper())
                .order_by(PriceForecastSnapshot.computed_at.desc())
                .limit(200)
            )
            latest_by_horizon: dict[str, PriceForecastSnapshot] = {}
            for row in result:
                if row.horizon not in latest_by_horizon:
                    latest_by_horizon[row.horizon] = row
                if len(latest_by_horizon) == len(HORIZONS):
                    break
            return latest_by_horizon

    async def get_horizon_consistency(self, symbol: str) -> dict | None:
        """Forecast Intelligence Upgrade -- Multi-Horizon Consistency.
        Reads each horizon's own latest already-computed snapshot (zero new
        forecast computation, zero extra I/O beyond the one query above)
        and reports whether they agree. See `compute_horizon_consistency`
        for what "agree" means and why horizons are never forced to."""
        latest_by_horizon = await self.get_latest_per_horizon(symbol)
        if not latest_by_horizon:
            return None
        directions = {h: row.direction for h, row in latest_by_horizon.items()}
        consistency = compute_horizon_consistency(directions)
        if consistency is None:
            return None
        consistency["by_horizon"] = {
            h: {
                "direction": row.direction,
                "probability_pct": row.probability_pct,
                "computed_at": row.computed_at.isoformat(),
            }
            for h, row in latest_by_horizon.items()
        }
        return consistency

    async def summarize_accuracy(self, symbol: str, horizon: str) -> dict | None:
        return await summarize_forecast_accuracy(self._session_factory, symbol.upper(), horizon)

    async def get_official_daily(
        self, symbols: tuple[str, ...]
    ) -> dict[str, PriceForecastSnapshot]:
        """Forecasting 2.0 (Part 34 Page 1): today's (UTC) official 24h
        forecast for each of `symbols` that has one -- a symbol with no
        row for today (e.g. insufficient data, or the daily job hasn't
        fired yet) is simply absent from the result, never a placeholder.
        One query for the whole roster, not one per symbol."""
        today = datetime.now(UTC).date()
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(PriceForecastSnapshot).where(
                    PriceForecastSnapshot.symbol.in_(symbols),
                    PriceForecastSnapshot.horizon == "24h",
                    PriceForecastSnapshot.is_official_daily.is_(True),
                    PriceForecastSnapshot.official_forecast_date == today,
                )
            )
            return {row.symbol: row for row in rows}

    async def get_official_history(
        self, symbol: str, limit: int = 30
    ) -> list[PriceForecastSnapshot]:
        """Forecasting 2.0 (Part 34 Page 2/3): past official daily 24h
        forecasts for one symbol, most recent first -- includes graded
        outcome fields (realized_price/error_pct/direction_correct/
        target_reached/excursions/error_type) once grade_price_forecasts
        has filled them in, still None until then."""
        async with self._session_factory() as session:
            result = await session.scalars(
                select(PriceForecastSnapshot)
                .where(
                    PriceForecastSnapshot.symbol == symbol.upper(),
                    PriceForecastSnapshot.horizon == "24h",
                    PriceForecastSnapshot.is_official_daily.is_(True),
                )
                .order_by(PriceForecastSnapshot.official_forecast_date.desc())
                .limit(limit)
            )
            return list(result)

    async def get_agent_performance(self, symbols: tuple[str, ...]) -> list[dict]:
        """Forecasting 2.0 (Part 26 / Page 5): per (agent, symbol)
        direction accuracy across graded official daily forecasts. Joins
        `agent_forecasts` to their parent `price_forecast_snapshots` --
        reuses AgentForecast rows already persisted at forecast time
        (Part 10/11), no new data collection, no second agent system."""
        min_sample_size = get_settings().agent_performance_min_sample_size
        async with self._session_factory() as session:
            rows = await session.execute(
                select(
                    AgentForecast.agent_name,
                    PriceForecastSnapshot.symbol,
                    PriceForecastSnapshot.direction_correct,
                )
                .join(
                    PriceForecastSnapshot,
                    AgentForecast.forecast_id == PriceForecastSnapshot.id,
                )
                .where(
                    PriceForecastSnapshot.symbol.in_(symbols),
                    PriceForecastSnapshot.is_official_daily.is_(True),
                    PriceForecastSnapshot.direction_correct.is_not(None),
                    AgentForecast.confidence_pct.is_not(None),
                )
            )
            graded = [(r.agent_name, r.symbol, r.direction_correct) for r in rows]
        return aggregate_agent_performance(graded, min_sample_size)

    async def get_official_performance(
        self, symbols: tuple[str, ...], since: datetime | None = None
    ) -> dict:
        """Forecasting 2.0 (Page 4, Performance): the overall (not
        per-agent) scorecard across every graded official daily forecast
        in `symbols` -- summary stats, a probability-calibration curve,
        and accuracy broken down by the regime the forecast was made in.
        Distinct from Agent Performance (Page 5, conditioned on
        AgentForecast rows) and Learning Center (Page 7, needs TWO
        regimes per agent before it says anything): this is the single
        top-level "is the official forecast surface any good" view, one
        query over price_forecast_snapshots, no new tables.

        `since` (Forecasting 2.0 weekly review digest): when given,
        restricts to forecasts GRADED at or after `since` --
        evaluated_at, not computed_at, since "how did we do this week"
        means "which calls resolved this week," not "which calls were
        made this week" (a forecast made near the end of a window won't
        have resolved yet, and excluding it here isn't a gap -- it's
        just not gradeable yet, same as every other None-until-graded
        field in this table). None (the default) keeps the existing
        all-time behavior the Performance page uses."""
        filters = [
            PriceForecastSnapshot.symbol.in_(symbols),
            PriceForecastSnapshot.is_official_daily.is_(True),
            PriceForecastSnapshot.direction_correct.is_not(None),
        ]
        if since is not None:
            filters.append(PriceForecastSnapshot.evaluated_at >= since)
        async with self._session_factory() as session:
            rows = list(
                await session.execute(
                    select(
                        PriceForecastSnapshot.probability_pct,
                        PriceForecastSnapshot.direction_correct,
                        PriceForecastSnapshot.error_pct,
                        PriceForecastSnapshot.target_reached,
                        PriceForecastSnapshot.regime_at_forecast,
                    ).where(*filters)
                )
            )

        summary = summarize_official_performance(
            [
                (
                    r.direction_correct,
                    float(r.error_pct) if r.error_pct is not None else None,
                    r.target_reached,
                )
                for r in rows
            ]
        )
        calibration = derive_official_calibration_curve(
            [(r.probability_pct, r.direction_correct) for r in rows]
        )
        regime_breakdown = derive_regime_performance_breakdown(
            [(r.regime_at_forecast, r.direction_correct) for r in rows if r.regime_at_forecast],
            get_settings().agent_performance_min_sample_size,
        )
        return {
            "summary": summary,
            "calibration": calibration,
            "regime_breakdown": regime_breakdown,
        }

    async def get_learning_insights(self, symbols: tuple[str, ...]) -> list[dict]:
        """Forecasting 2.0 (Part 33 / Page 7, Learning Center): regime-
        conditioned accuracy comparisons per (agent, symbol) -- same join
        as get_agent_performance, with regime_at_forecast (already
        persisted on every forecast, see PriceForecastSnapshot's own
        docstring) added to the grouping. No new data collection."""
        settings = get_settings()
        async with self._session_factory() as session:
            rows = await session.execute(
                select(
                    AgentForecast.agent_name,
                    PriceForecastSnapshot.symbol,
                    PriceForecastSnapshot.regime_at_forecast,
                    PriceForecastSnapshot.direction_correct,
                )
                .join(
                    PriceForecastSnapshot,
                    AgentForecast.forecast_id == PriceForecastSnapshot.id,
                )
                .where(
                    PriceForecastSnapshot.symbol.in_(symbols),
                    PriceForecastSnapshot.is_official_daily.is_(True),
                    PriceForecastSnapshot.direction_correct.is_not(None),
                    PriceForecastSnapshot.regime_at_forecast.is_not(None),
                    AgentForecast.confidence_pct.is_not(None),
                )
            )
            graded = [
                (r.agent_name, r.symbol, r.regime_at_forecast, r.direction_correct) for r in rows
            ]
        return derive_learning_insights(
            graded,
            settings.learning_insight_min_sample_size,
            settings.learning_insight_min_gap_pct,
        )

    async def get_forecast_detail(self, forecast_id: int) -> dict | None:
        """Forecasting 2.0 (Page 3, Forecast Details): the full input
        snapshot and complete per-agent evidence for ONE official daily
        forecast -- everything `_serialize_official` already exposes plus
        the fields that only matter for a drill-down (checkpoints,
        distribution, key_levels, reference_timestamp, forecast_version,
        invalidation lineage, baseline comparisons). Unlike Error Lab
        (which only surfaces agent evidence for WRONG calls), this returns
        every AgentForecast row regardless of outcome, since a drill-down
        is opt-in per forecast rather than a triage list. Only ever
        resolves official daily rows (is_official_daily is True) -- the
        much larger set of intraday recompute snapshots isn't part of the
        Forecasting 2.0 surface and has no per-agent evidence persisted
        for it anyway. None when the id doesn't match an official row."""
        async with self._session_factory() as session:
            snapshot = await session.scalar(
                select(PriceForecastSnapshot).where(
                    PriceForecastSnapshot.id == forecast_id,
                    PriceForecastSnapshot.is_official_daily.is_(True),
                )
            )
            if snapshot is None:
                return None
            agents = list(
                await session.scalars(
                    select(AgentForecast)
                    .where(AgentForecast.forecast_id == forecast_id)
                    .order_by(AgentForecast.agent_name)
                )
            )
        return {"forecast": snapshot, "agents": agents}

    async def get_error_lab(self, symbols: tuple[str, ...], limit: int = 20) -> list[dict]:
        """Forecasting 2.0 (Part 27/28 / Page 6): the most recent official
        daily forecasts that graded WRONG (direction_correct is False),
        most recent first, each with its linked per-agent evidence
        (AgentForecast rows) -- "what each source said when we got this
        wrong," not a fabricated root-cause narrative beyond what
        error_type (see classify_error_type) already honestly encodes."""
        async with self._session_factory() as session:
            wrong = list(
                await session.scalars(
                    select(PriceForecastSnapshot)
                    .where(
                        PriceForecastSnapshot.symbol.in_(symbols),
                        PriceForecastSnapshot.is_official_daily.is_(True),
                        PriceForecastSnapshot.direction_correct.is_(False),
                    )
                    .order_by(PriceForecastSnapshot.official_forecast_date.desc())
                    .limit(limit)
                )
            )
            if not wrong:
                return []
            forecast_ids = [row.id for row in wrong]
            agent_rows = list(
                await session.scalars(
                    select(AgentForecast).where(AgentForecast.forecast_id.in_(forecast_ids))
                )
            )
        agents_by_forecast: dict[int, list[AgentForecast]] = defaultdict(list)
        for row in agent_rows:
            agents_by_forecast[row.forecast_id].append(row)

        return [
            {
                "forecast": snapshot,
                "agents": agents_by_forecast.get(snapshot.id, []),
            }
            for snapshot in wrong
        ]


def build_forecast_engine() -> ForecastEngine:
    from app.database.redis import get_redis
    from app.database.session import get_session_factory
    from app.services.global_score.engine import GlobalScoreEngine
    from app.services.news.repository import NewsRepository
    from app.services.scenarios.engine import ScenarioEngine
    from app.services.signals.engine import SignalEngine
    from app.services.technical.provider import TechnicalAnalysisProvider

    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    scenario_engine = ScenarioEngine(session_factory, global_score_engine)
    explanation_engine = ExplanationEngine(
        session_factory,
        signal_engine,
        regime_detector,
        news_repository,
        global_score_engine,
        scenario_engine,
    )
    technical_engine = TechnicalAnalysisEngine(
        session_factory, TechnicalAnalysisProvider(session_factory)
    )

    return ForecastEngine(
        session_factory,
        ProbabilityEngine(session_factory),
        PredictionQualityEngine(session_factory),
        technical_engine,
        explanation_engine,
        EconomicCalendarEngine(session_factory),
        SentimentEngine(session_factory, news_repository),
        CorrelationEngine(session_factory),
        WhaleIntelligenceEngine(session_factory),
        OnChainIntelligenceEngine(),
        PatternEngine(session_factory),
    )
