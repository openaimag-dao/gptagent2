"""Executive Market Summary -- a panel below the Overview page's AI Forecast
Center answering "what should I know right now?" entirely out of numbers
other engines already compute:

- Overall score/regime/risk/committee decision are read straight off the
  latest `WatchdogSnapshot` (same "never duplicate calculations already
  performed by Committee/Consensus/Scenario/Risk" reuse this project's
  Forecast Center already follows) rather than re-invoking the agent
  orchestrator, Committee, or GlobalScore from scratch.
- Bullish/bearish factors are read off real, already-labeled signals only:
  `TechnicalAnalysisSnapshot.active_signals` (RSI/MACD/cross/trend events
  the technical engine already detected), Consensus's own bullish/bearish
  agent buckets and evidence, `ExplanationEngine`'s already-tagged
  supporting news, the Crypto Fear & Greed classification, the ETF proxy's
  own classification, and Whale Intelligence's own funding-rate reading --
  never an invented sentiment score.
- The AI Action (Strong Buy...No Trade) is a presentation-only mapping of
  the AI Investment Committee's own decision/confidence and
  GlobalScoreEngine's own risk_score onto an 8-tier scale -- no new trading
  model, and always carries the real numbers behind it as its reason.
- No new persistence: every input here is already recomputed every analysis
  cycle by its own engine/scheduler job, so re-reading them on each
  dashboard refresh is enough to satisfy "update every analysis cycle"
  without a redundant new job.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import WatchdogSnapshot
from app.services.analysis.regime import MarketRegime
from app.services.etf.engine import ETFIntelligenceEngine
from app.services.explanation.engine import ExplanationEngine
from app.services.forecast.engine import (
    _onchain_confidence as _onchain_activity_score,  # honest-availability helper, reused as-is
)
from app.services.forecast.engine import (
    classify_direction_label,
    derive_regime_label,
    derive_risk_meter,
)
from app.services.global_score.engine import GlobalScoreEngine
from app.services.onchain.engine import OnChainIntelligenceEngine
from app.services.sentiment.engine import SentimentEngine
from app.services.technical.engine import TechnicalAnalysisEngine
from app.services.whales.engine import WhaleIntelligenceEngine

# Technical Analysis Engine's own detected event names
# (app/services/technical/signals.py) mapped onto a bullish/bearish tag and
# a human-readable label -- no new detection, just a presentation lookup
# over signals that engine already persisted this cycle.
_SIGNAL_FACTORS: dict[str, tuple[str, str]] = {
    "RSIOverbought": ("bearish", "Overbought RSI"),
    "RSIOversold": ("bullish", "Oversold RSI (potential bounce)"),
    "GoldenCross": ("bullish", "Golden Cross (SMA50 crossed above SMA200)"),
    "DeathCross": ("bearish", "Death Cross (SMA50 crossed below SMA200)"),
    "MACDBullishCrossover": ("bullish", "MACD bullish crossover"),
    "MACDBearishCrossover": ("bearish", "MACD bearish crossover"),
    "TrendAcceleration": ("bullish", "Trend accelerating"),
    "TrendWeakening": ("bearish", "Trend weakening"),
    "TechnicalBullish": ("bullish", "Technical score bullish"),
    "TechnicalBearish": ("bearish", "Technical score bearish"),
}

# Whale Intelligence's own funding-rate reading: near zero is a balanced,
# healthy market; at or beyond this magnitude is the same "extreme/crowded
# positioning" threshold `_whale_confidence` (forecast/engine.py) already
# treats as maximally informative -- reused here as a bullish/bearish
# read rather than a fresh threshold.
_HEALTHY_FUNDING_ABS = 0.0001
_EXTREME_FUNDING_ABS = 0.0005

_GREED_LABELS = {"Greed", "Extreme Greed"}
_FEAR_LABELS = {"Fear", "Extreme Fear"}


def _agent_factor_line(agent: str, evidence: str | None, side: str) -> str:
    """A consensus agent's own evidence excerpt, formatted as one factor
    bullet -- strips the leading "- " list-marker some agents' summaries
    use (app/services/common/formatting.py's asset-line convention) since
    it reads oddly restated inside a checklist bullet, but never changes
    the evidence text's substance."""
    name = agent.replace("_", " ").title()
    if not evidence:
        return f"{name} {side}"
    return f"{name}: {evidence.lstrip('- ').strip()}"


def compose_market_factors(
    active_signals: list[str] | None,
    consensus: dict | None,
    supporting_news: list[dict] | None,
    fear_greed_classification: str | None,
    etf_proxy: dict | None,
    whale_snapshot: dict | None,
) -> tuple[list[str], list[str]]:
    """Pure function: assembles the bullish/bearish factor checklists from
    only real, already-labeled signals -- returns [] on either side rather
    than padding with a fabricated factor when a source has nothing to say
    this cycle."""
    bullish: list[str] = []
    bearish: list[str] = []

    for signal in active_signals or []:
        mapped = _SIGNAL_FACTORS.get(signal)
        if mapped is None:
            continue
        side, label = mapped
        (bullish if side == "bullish" else bearish).append(label)

    if consensus:
        evidence = consensus.get("agent_evidence") or {}
        for agent in consensus.get("bullish_agents") or []:
            bullish.append(_agent_factor_line(agent, evidence.get(agent), "bullish"))
        for agent in consensus.get("bearish_agents") or []:
            bearish.append(_agent_factor_line(agent, evidence.get(agent), "bearish"))

    for item in supporting_news or []:
        sentiment = item.get("sentiment")
        if sentiment == "bullish":
            bullish.append(f"Positive news: {item.get('title')}")
        elif sentiment == "bearish":
            bearish.append(f"Negative news: {item.get('title')}")

    if fear_greed_classification in _GREED_LABELS:
        bullish.append(f"Crypto Fear & Greed: {fear_greed_classification}")
    elif fear_greed_classification in _FEAR_LABELS:
        bearish.append(f"Crypto Fear & Greed: {fear_greed_classification}")

    if etf_proxy is not None and etf_proxy.get("available"):
        classification = etf_proxy.get("classification")
        if classification == "leaning_institutional_buying":
            bullish.append("ETF-flow proxy leans institutional buying (news-sentiment proxy)")
        elif classification == "leaning_institutional_selling":
            bearish.append("ETF-flow proxy leans institutional selling (news-sentiment proxy)")

    if whale_snapshot is not None and whale_snapshot.get("available"):
        funding = whale_snapshot.get("funding_rate")
        if funding is not None:
            if abs(funding) < _HEALTHY_FUNDING_ABS:
                bullish.append(f"Healthy funding rate ({funding:.4%})")
            elif abs(funding) >= _EXTREME_FUNDING_ABS:
                bearish.append(f"Extreme funding rate -- crowded positioning ({funding:.4%})")

    return bullish, bearish


def classify_ai_action(
    committee_decision: str | None,
    committee_confidence_pct: float | None,
    risk_score: int | None,
) -> tuple[str, str]:
    """Pure function: maps the AI Investment Committee's own decision
    (BUY/SELL/HOLD), its own confidence_pct, and GlobalScoreEngine's own
    risk_score onto the 8-tier action scale a retail reader expects (Strong
    Buy...No Trade) -- presentation composition over 3 numbers this project
    already computes every cycle, not a new trading model. Always returns a
    one-line reason citing the real inputs behind the tier."""
    if committee_decision is None or committee_confidence_pct is None:
        return "No Trade", "Insufficient agent consensus this cycle to act on."

    confidence = committee_confidence_pct
    risk = risk_score if risk_score is not None else 50

    if committee_decision == "BUY":
        if confidence >= 80:
            return (
                "Strong Buy",
                f"Committee BUY at {confidence:.0f}% confidence, high agent agreement.",
            )
        if confidence >= 60:
            return "Buy", f"Committee BUY at {confidence:.0f}% confidence."
        return (
            "Accumulate",
            f"Committee leans BUY at {confidence:.0f}% confidence -- "
            "gradual entry favored over a full position.",
        )

    if committee_decision == "SELL":
        if risk >= 70:
            return (
                "Reduce Risk",
                f"Committee SELL at {confidence:.0f}% confidence with "
                f"elevated risk score ({risk}/100).",
            )
        if confidence >= 80:
            return "Sell", f"Committee SELL at {confidence:.0f}% confidence, high agent agreement."
        return (
            "Take Profit",
            f"Committee leans SELL at {confidence:.0f}% confidence -- "
            "favor locking in gains over a full exit.",
        )

    if confidence < 40:
        return (
            "No Trade",
            f"Committee HOLD with low confidence ({confidence:.0f}%) -- no clear edge this cycle.",
        )
    return "Hold", f"Committee HOLD at {confidence:.0f}% confidence."


def compose_summary(
    bias: str,
    overall_score: int | None,
    regime_label: str,
    volatility: float | None,
    sentiment_score: int | None,
    risk_meter: str,
    risk_score: int | None,
    action: str,
    action_reason: str,
) -> str:
    """Pure function: 3-5 sentence narrative composed entirely from the
    fields already computed above -- deterministic string composition, the
    same style ExplanationEngine/WatchdogEngine's own narrative fields
    already use, never an LLM call."""
    sentences: list[str] = []

    if overall_score is not None:
        sentences.append(
            f"The market is {bias.lower()} with an overall score of {overall_score}/100."
        )
    else:
        sentences.append(f"The market is {bias.lower()}.")

    vol_part = (
        f"volatility at {volatility:.0f}/100"
        if volatility is not None
        else "volatility data unavailable"
    )
    sentences.append(f"{regime_label} conditions, {vol_part}.")

    if sentiment_score is not None:
        mood = (
            "positive"
            if sentiment_score >= 60
            else "negative"
            if sentiment_score <= 40
            else "neutral"
        )
        sentences.append(f"Market sentiment is {mood} at {sentiment_score}/100.")

    risk_part = f" ({risk_score}/100)" if risk_score is not None else ""
    sentences.append(f"Risk is assessed as {risk_meter}{risk_part}.")

    sentences.append(f"AI recommendation: {action} -- {action_reason}")

    return " ".join(sentences)


class ExecutiveSummaryEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        global_score_engine: GlobalScoreEngine,
        technical_engine: TechnicalAnalysisEngine,
        sentiment_engine: SentimentEngine,
        explanation_engine: ExplanationEngine,
        whale_engine: WhaleIntelligenceEngine,
        onchain_engine: OnChainIntelligenceEngine,
        etf_engine: ETFIntelligenceEngine,
    ) -> None:
        self._session_factory = session_factory
        self._global_score_engine = global_score_engine
        self._technical_engine = technical_engine
        self._sentiment_engine = sentiment_engine
        self._explanation_engine = explanation_engine
        self._whale_engine = whale_engine
        self._onchain_engine = onchain_engine
        self._etf_engine = etf_engine

    async def _latest_watchdog_snapshot(self) -> WatchdogSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(WatchdogSnapshot).order_by(WatchdogSnapshot.computed_at.desc()).limit(1)
            )

    async def compute(self, symbol: str = "BTC") -> dict | None:
        symbol = symbol.upper()
        watchdog = await self._latest_watchdog_snapshot()
        if watchdog is None:
            return None

        global_score = await self._global_score_engine.get_latest()
        technical_snapshot = await self._technical_engine.get_latest(symbol)
        sentiment_snapshot = await self._sentiment_engine.get_latest()
        explanation = await self._explanation_engine.build(symbol)
        whale_snapshot = await self._whale_engine.get_snapshot(symbol)
        onchain_snapshot = await self._onchain_engine.get_snapshot(symbol)
        etf_proxy = await self._etf_engine.get_flow_proxy()

        consensus = watchdog.consensus
        bias = (
            classify_direction_label(
                round(consensus["bullish_pct"]), round(consensus["bearish_pct"])
            )
            if consensus
            else "Neutral"
        )

        action, action_reason = classify_ai_action(
            watchdog.committee_decision, watchdog.committee_confidence_pct, watchdog.risk_score
        )

        regime = MarketRegime(watchdog.regime) if watchdog.regime else None
        volatility = float(watchdog.volatility) if watchdog.volatility is not None else None
        trend_strength = (
            float(technical_snapshot.trend_strength)
            if technical_snapshot is not None and technical_snapshot.trend_strength is not None
            else None
        )
        regime_label = derive_regime_label(regime, volatility, trend_strength)
        risk_meter = derive_risk_meter(watchdog.risk_score, regime)

        bullish_factors, bearish_factors = compose_market_factors(
            technical_snapshot.active_signals if technical_snapshot is not None else [],
            consensus,
            explanation.get("supporting_news"),
            sentiment_snapshot.fear_greed_classification
            if sentiment_snapshot is not None
            else None,
            etf_proxy,
            whale_snapshot,
        )

        market_health = {
            "liquidity": watchdog.liquidity_score,
            "volatility": volatility,
            "momentum": min(100.0, trend_strength) if trend_strength is not None else None,
            "sentiment": sentiment_snapshot.global_sentiment_score
            if sentiment_snapshot is not None
            else None,
            "institutional_activity": global_score.institutional_activity_score
            if global_score is not None
            else None,
            "onchain_activity": _onchain_activity_score(onchain_snapshot),
            "news_quality": sentiment_snapshot.news_sentiment_score
            if sentiment_snapshot is not None
            else None,
        }

        summary = compose_summary(
            bias,
            watchdog.global_score,
            regime_label,
            volatility,
            sentiment_snapshot.global_sentiment_score if sentiment_snapshot is not None else None,
            risk_meter,
            watchdog.risk_score,
            action,
            action_reason,
        )

        return {
            "symbol": symbol,
            "computed_at": datetime.now(UTC).isoformat(),
            "watchdog_computed_at": watchdog.computed_at.isoformat(),
            "overall_score": watchdog.global_score,
            "bias": bias,
            "summary": summary,
            "bullish_factors": bullish_factors,
            "bearish_factors": bearish_factors,
            "market_health": market_health,
            "action": action,
            "action_reason": action_reason,
            "risk_meter": risk_meter,
            "regime": regime_label,
        }


def build_executive_summary_engine() -> ExecutiveSummaryEngine:
    from app.database.redis import get_redis
    from app.database.session import get_session_factory
    from app.services.analysis.regime import RegimeDetector
    from app.services.market.repository import MarketRepository
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

    return ExecutiveSummaryEngine(
        session_factory,
        global_score_engine,
        technical_engine,
        SentimentEngine(session_factory, news_repository),
        explanation_engine,
        WhaleIntelligenceEngine(session_factory),
        OnChainIntelligenceEngine(),
        ETFIntelligenceEngine(news_repository),
    )
