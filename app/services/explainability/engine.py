""" "Why AI Thinks This" -- a full, per-engine breakdown of the current
prediction: for each of Technical Analysis/News/On-chain/Whales/Macro/
Sentiment/Correlations/Historical Patterns, a Signal (direction), a
Confidence (0-100), a Weight (this engine's share of the final vote), and
an Explanation (real evidence text) -- so the final prediction is fully
traceable back to the real numbers behind it.

Composes entirely from data other engines already computed, following the
exact reuse pattern established by ForecastEngine/ExecutiveSummaryEngine:

- Signal/Weight/Explanation for Technical Analysis, News, Sentiment, and
  Macro come straight off the latest `WatchdogSnapshot.consensus` (the
  same persisted Consensus vote tally Forecast Center and Executive
  Summary already read) -- no re-invoking the agent orchestrator.
- Confidence for those same four, plus On-chain/Whales/Correlations,
  reuses `ForecastEngine`'s own `_confidence_breakdown()` formulas
  (imported directly, not re-implemented) -- Macro's confidence is
  corrected to read `GlobalScoreEngine.macro_pressure_score` (a genuine
  macro-specific number) rather than the whole-market
  `WatchdogSnapshot.confidence_score` Forecast Center's row happens to use.
- On-chain is honestly reported unavailable (with the real reason string)
  -- `OnChainIntelligenceEngine` is a documented no-data-source scaffold.
- Whales/Correlations/Historical Patterns have no dedicated agent vote, so
  Weight is honestly `None` for them; their Signal/Explanation are
  composed from real fields (`WhaleIntelligenceEngine`'s own
  classification/funding rate, `CorrelationEngine`'s own 30-day Pearson
  correlations, `ExplanationEngine`'s own historical analog matches).
- `ExplanationEngine.build()` is called once, unmodified, for the
  historical-examples data and folded into the response alongside the new
  `engine_breakdown` -- this module adds to that dict, it does not
  duplicate any of its computation.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import WatchdogSnapshot
from app.services.analysis.correlation import CorrelationEngine
from app.services.explanation.engine import ExplanationEngine
from app.services.forecast.engine import (
    _correlation_confidence,
    _distance_from_neutral,
    _onchain_confidence,
    _whale_confidence,
    classify_direction_label,
)
from app.services.global_score.engine import GlobalScoreEngine
from app.services.onchain.engine import OnChainIntelligenceEngine
from app.services.sentiment.engine import SentimentEngine
from app.services.technical.engine import TechnicalAnalysisEngine
from app.services.whales.engine import WhaleIntelligenceEngine

# Consensus agent keys (app/services/agents/*.py) that map 1:1 onto a
# requested category -- reused to pull that agent's real bullish/bearish/
# neutral bucket, evidence excerpt, and vote-weight share straight off
# WatchdogSnapshot.consensus, never re-derived.
_CATEGORY_AGENT_KEYS: dict[str, str] = {
    "Technical Analysis": "technical",
    "News": "news",
    "Sentiment": "sentiment",
    "Macro": "macro",
}


@dataclass(frozen=True)
class EngineBreakdownRow:
    name: str
    signal: str | None  # None = honestly no directional read this cycle
    confidence: int | None
    weight: float | None  # % share of the Consensus vote; None where no dedicated agent exists
    explanation: str | None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "signal": self.signal,
            "confidence": self.confidence,
            "weight": self.weight,
            "explanation": self.explanation,
        }


def _agent_signal(agent_key: str, consensus: dict | None) -> str | None:
    """Pure function: which bucket (bullish/bearish/neutral/unavailable)
    this agent landed in this cycle, straight off the real Consensus
    tally. None (not "Neutral") when the agent reported no direction at
    all -- an honest "no read," distinct from a real neutral vote."""
    if consensus is None:
        return None
    if agent_key in (consensus.get("bullish_agents") or []):
        return "Bullish"
    if agent_key in (consensus.get("bearish_agents") or []):
        return "Bearish"
    if agent_key in (consensus.get("neutral_agents") or []):
        return "Neutral"
    return None


def _agent_explanation(agent_key: str, consensus: dict | None) -> str | None:
    """Pure function: the agent's own real evidence excerpt (already
    computed by `agent_evidence_excerpt()`, shared by Consensus/Committee)
    -- strips the leading "- " list-marker some agents' summaries use
    (app/services/common/formatting.py's asset-line convention) since it
    reads oddly restated as a standalone sentence, but never changes the
    evidence text's substance."""
    if consensus is None:
        return None
    evidence = (consensus.get("agent_evidence") or {}).get(agent_key)
    if not evidence:
        return None
    return evidence.lstrip("- ").strip()


def _agent_weight(agent_key: str, consensus: dict | None) -> float | None:
    if consensus is None:
        return None
    return (consensus.get("agent_weights") or {}).get(agent_key)


def _whale_signal(whale_snapshot: dict) -> str | None:
    if not whale_snapshot.get("available"):
        return None
    classification = whale_snapshot.get("classification")
    return classification.replace("_", " ").title() if classification else None


def _whale_explanation(whale_snapshot: dict) -> str | None:
    if not whale_snapshot.get("available"):
        reason = whale_snapshot.get("reason")
        return f"Unavailable this cycle: {reason}" if reason else None
    parts = []
    classification = whale_snapshot.get("classification")
    if classification:
        parts.append(f"positioning classified {classification.replace('_', ' ')}")
    ratio = whale_snapshot.get("long_short_ratio")
    if ratio is not None:
        parts.append(f"long/short ratio {ratio:.2f}")
    funding = whale_snapshot.get("funding_rate")
    if funding is not None:
        parts.append(f"funding rate {funding:.4%}")
    if not parts:
        return "Derivatives data available but no positioning read this cycle."
    return "Derivatives " + ", ".join(parts) + "."


def _correlation_explanation(correlations: list, symbol: str) -> str | None:
    """Pure function: the real 30-day Pearson correlations involving this
    symbol, strongest-first -- the same rows `_correlation_confidence`
    already averages, just quoted individually instead of collapsed into
    one number."""
    matches = [
        (c.symbol_a if c.symbol_b == symbol else c.symbol_b, float(c.correlation))
        for c in correlations
        if c.window_days == 30 and symbol in (c.symbol_a, c.symbol_b)
    ]
    if not matches:
        return None
    matches.sort(key=lambda pair: abs(pair[1]), reverse=True)
    parts = [f"{symbol}-{other}: {corr:+.2f}" for other, corr in matches[:3]]
    return ", ".join(parts) + " (30-day Pearson)"


def _historical_signal_and_explanation(
    historical_examples: list[dict],
) -> tuple[str | None, str | None]:
    """Pure function: derives a directional read and a plain-language
    explanation from ExplanationEngine's own historical analog matches --
    never a new similarity search, just an honest read of the same
    forward-return data already fetched."""
    if not historical_examples:
        return None, "No similar historical periods found yet."

    returns = [
        e["forward_return_7d_pct"]
        for e in historical_examples
        if e["forward_return_7d_pct"] is not None
    ]
    signal = None
    if returns:
        avg_return = sum(returns) / len(returns)
        if avg_return > 0.5:
            signal = "Bullish"
        elif avg_return < -0.5:
            signal = "Bearish"
        else:
            signal = "Neutral"

    best = max(historical_examples, key=lambda e: e["similarity_score"])
    plural = "s" if len(historical_examples) != 1 else ""
    explanation = (
        f"{len(historical_examples)} similar historical period{plural} found "
        f"(most similar: {best['match_timestamp'][:10]}, "
        f"{best['similarity_score']:.0f}% similar, {best['regime'] or 'unknown'} regime)"
    )
    if returns:
        avg_return = sum(returns) / len(returns)
        explanation += f". Average 7-day forward return: {avg_return:+.2f}%."
    return signal, explanation


def _historical_confidence(historical_examples: list[dict]) -> int | None:
    scores = [e["similarity_score"] for e in historical_examples]
    if not scores:
        return None
    return round(min(100.0, sum(scores) / len(scores)))


class ExplainabilityEngine:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        explanation_engine: ExplanationEngine,
        global_score_engine: GlobalScoreEngine,
        technical_engine: TechnicalAnalysisEngine,
        sentiment_engine: SentimentEngine,
        correlation_engine: CorrelationEngine,
        whale_engine: WhaleIntelligenceEngine,
        onchain_engine: OnChainIntelligenceEngine,
    ) -> None:
        self._session_factory = session_factory
        self._explanation_engine = explanation_engine
        self._global_score_engine = global_score_engine
        self._technical_engine = technical_engine
        self._sentiment_engine = sentiment_engine
        self._correlation_engine = correlation_engine
        self._whale_engine = whale_engine
        self._onchain_engine = onchain_engine

    async def _latest_watchdog_snapshot(self) -> WatchdogSnapshot | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(WatchdogSnapshot).order_by(WatchdogSnapshot.computed_at.desc()).limit(1)
            )

    async def build(self, symbol: str = "BTC") -> dict:
        symbol = symbol.upper()

        explanation = await self._explanation_engine.build(symbol)
        watchdog = await self._latest_watchdog_snapshot()
        global_score = await self._global_score_engine.get_latest()
        technical_snapshot = await self._technical_engine.get_latest(symbol)
        sentiment_snapshot = await self._sentiment_engine.get_latest()
        correlations = await self._correlation_engine.get_latest()
        whale_snapshot = await self._whale_engine.get_snapshot(symbol)
        onchain_snapshot = await self._onchain_engine.get_snapshot(symbol)

        consensus = watchdog.consensus if watchdog is not None else None

        def _agent_row(name: str, confidence: int | None) -> EngineBreakdownRow:
            agent_key = _CATEGORY_AGENT_KEYS[name]
            return EngineBreakdownRow(
                name=name,
                signal=_agent_signal(agent_key, consensus),
                confidence=confidence,
                weight=_agent_weight(agent_key, consensus),
                explanation=_agent_explanation(agent_key, consensus),
            )

        macro_confidence = (
            _distance_from_neutral(global_score.macro_pressure_score)
            if global_score is not None
            else None
        )
        historical_signal, historical_explanation = _historical_signal_and_explanation(
            explanation.get("historical_examples") or []
        )

        rows = [
            _agent_row(
                "Technical Analysis",
                round(technical_snapshot.confidence)
                if technical_snapshot is not None and technical_snapshot.confidence is not None
                else None,
            ),
            _agent_row(
                "News",
                _distance_from_neutral(
                    sentiment_snapshot.news_sentiment_score
                    if sentiment_snapshot is not None
                    else None
                ),
            ),
            _agent_row(
                "Sentiment",
                _distance_from_neutral(
                    sentiment_snapshot.global_sentiment_score
                    if sentiment_snapshot is not None
                    else None
                ),
            ),
            _agent_row("Macro", macro_confidence),
            EngineBreakdownRow(
                name="On-chain",
                signal=None,
                confidence=_onchain_confidence(onchain_snapshot),
                weight=None,
                explanation=onchain_snapshot.get("reason"),
            ),
            EngineBreakdownRow(
                name="Whales",
                signal=_whale_signal(whale_snapshot),
                confidence=_whale_confidence(whale_snapshot),
                weight=None,
                explanation=_whale_explanation(whale_snapshot),
            ),
            EngineBreakdownRow(
                name="Correlations",
                signal=None,
                confidence=_correlation_confidence(correlations, symbol),
                weight=None,
                explanation=_correlation_explanation(correlations, symbol),
            ),
            EngineBreakdownRow(
                name="Historical Patterns",
                signal=historical_signal,
                confidence=_historical_confidence(explanation.get("historical_examples") or []),
                weight=None,
                explanation=historical_explanation,
            ),
        ]

        final_bias = (
            classify_direction_label(
                round(consensus["bullish_pct"]), round(consensus["bearish_pct"])
            )
            if consensus
            else None
        )

        explanation["engine_breakdown"] = [row.to_dict() for row in rows]
        explanation["final_prediction"] = {
            "bias": final_bias,
            "agreement_score": consensus.get("agreement_score") if consensus else None,
            "committee_decision": watchdog.committee_decision if watchdog is not None else None,
            "committee_recommendation": watchdog.committee_recommendation
            if watchdog is not None
            else None,
        }
        return explanation


def build_explainability_engine() -> ExplainabilityEngine:
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

    return ExplainabilityEngine(
        session_factory,
        explanation_engine,
        global_score_engine,
        technical_engine,
        SentimentEngine(session_factory, news_repository),
        CorrelationEngine(session_factory),
        WhaleIntelligenceEngine(session_factory),
        OnChainIntelligenceEngine(),
    )
