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
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import EconomicCalendarEvent, PriceForecastSnapshot, WatchdogSnapshot
from app.services.analysis.correlation import CorrelationEngine
from app.services.analysis.regime import MarketRegime, RegimeDetector
from app.services.analysis.report import derive_risk_level
from app.services.calendar.engine import EconomicCalendarEngine
from app.services.conviction.engine import classify_conviction
from app.services.explanation.engine import ExplanationEngine
from app.services.history.registry import find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.market.repository import MarketRepository
from app.services.onchain.engine import OnChainIntelligenceEngine
from app.services.probability.engine import ProbabilityEngine
from app.services.quality.engine import PredictionQualityEngine
from app.services.sentiment.engine import SentimentEngine
from app.services.technical.engine import TechnicalAnalysisEngine
from app.services.whales.engine import WhaleIntelligenceEngine

logger = logging.getLogger(__name__)

# horizon label -> horizon_periods on Timeframe.DAILY (which IS calendar
# days), so 24h/3d/7d/30d need no new multi-horizon engine -- just four
# distinct `horizon` values on the same ProbabilityEngine.
HORIZONS: dict[str, int] = {"24h": 1, "3d": 3, "7d": 7, "30d": 30}


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
    if atr is None or atr <= 0 or current_price <= 0:
        return []

    mean_price = current_price * (1 + avg_forward_return_pct / 100)
    std = atr

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


async def grade_price_forecasts(
    session_factory: async_sessionmaker[AsyncSession], symbol: str, model: type
) -> int:
    """Fills in `realized_price`/`error_pct`/`evaluated_at` on every
    ungraded `PriceForecastSnapshot` row whose horizon has actually
    elapsed in stored history -- mirrors
    app.services.learning.engine.evaluate_predictions()'s index-by-
    timestamp join exactly (same reasoning: a forecast only becomes
    gradable once real history reaches that far, never guessed). Returns
    how many rows were graded this call."""
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

            db_row = await session.get(PriceForecastSnapshot, snapshot.id)
            db_row.realized_price = realized_price
            db_row.error_pct = round(error_pct, 4)
            db_row.evaluated_at = datetime.now(UTC)
            graded += 1
        await session.commit()
    return graded


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

    async def _latest_watchdog_snapshot(self) -> WatchdogSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(WatchdogSnapshot).order_by(WatchdogSnapshot.computed_at.desc()).limit(1)
            )

    async def _confidence_breakdown(
        self, symbol: str, technical_confidence: float | None, watchdog: WatchdogSnapshot | None
    ) -> list[ConfidenceRow]:
        sentiment_snapshot = await self._sentiment_engine.get_latest()
        correlations = await self._correlation_engine.get_latest()
        whale_snapshot = await self._whale_engine.get_snapshot(symbol)
        onchain_snapshot = await self._onchain_engine.get_snapshot(symbol)

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

    async def compute(self, symbol: str, horizon_label: str = "24h") -> dict | None:
        horizon_periods = HORIZONS.get(horizon_label)
        if horizon_periods is None:
            return None

        config = find_symbol_config(symbol)
        if config is None:
            return None

        rows = await get_series(self._session_factory, config.model, config.symbol, Timeframe.DAILY)
        if not rows:
            return None
        latest = rows[-1]
        current_price = float(latest.close)
        atr = float(latest.atr) if latest.atr is not None else None

        probability_snapshot = await self._probability_engine.compute_and_store(
            config.symbol, config.model, Timeframe.DAILY, horizon=horizon_periods
        )
        if probability_snapshot is None:
            return None

        quality = await self._quality_engine.evaluate(config.symbol, config.model, Timeframe.DAILY)
        confidence_pct = max(
            probability_snapshot.prob_up_pct,
            probability_snapshot.prob_down_pct,
            probability_snapshot.prob_flat_pct,
        )
        conviction = classify_conviction(
            confidence_pct,
            sample_size=probability_snapshot.sample_size,
            brier_score=quality["brier_score"] if quality else None,
            evaluated_predictions=quality["evaluated_predictions"] if quality else None,
        )

        avg_forward_return_pct = float(probability_snapshot.avg_forward_return_pct)
        target_price = compute_price_target(current_price, avg_forward_return_pct)
        path = compute_price_path(current_price, avg_forward_return_pct)
        distribution = compute_probability_distribution(current_price, avg_forward_return_pct, atr)
        direction_label = classify_direction_label(
            probability_snapshot.prob_up_pct, probability_snapshot.prob_down_pct
        )

        technical_snapshot = await self._technical_engine.get_latest(config.symbol)
        watchdog = await self._latest_watchdog_snapshot()
        explanation = await self._explanation_engine.build(config.symbol)
        confidence_breakdown = await self._confidence_breakdown(
            config.symbol,
            float(technical_snapshot.confidence)
            if technical_snapshot is not None and technical_snapshot.confidence is not None
            else None,
            watchdog,
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
            "trend_strength": float(technical_snapshot.trend_strength)
            if technical_snapshot is not None and technical_snapshot.trend_strength is not None
            else None,
            "price_path": path,
            "probability_distribution": distribution,
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
        }

        await self._persist(payload, latest.timestamp, conviction["tier"])
        return payload

    async def _persist(
        self, payload: dict, reference_timestamp: datetime, confidence_tier: str
    ) -> None:
        async with self._session_factory() as session:
            session.add(
                PriceForecastSnapshot(
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
                )
            )
            await session.commit()

    async def get_latest_history(self, symbol: str, limit: int = 20) -> list[PriceForecastSnapshot]:
        async with self._session_factory() as session:
            result = await session.scalars(
                select(PriceForecastSnapshot)
                .where(PriceForecastSnapshot.symbol == symbol.upper())
                .order_by(PriceForecastSnapshot.computed_at.desc())
                .limit(limit)
            )
            return list(result)

    async def summarize_accuracy(self, symbol: str, horizon: str) -> dict | None:
        return await summarize_forecast_accuracy(self._session_factory, symbol.upper(), horizon)


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
    )
