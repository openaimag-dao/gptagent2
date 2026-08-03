""" "Why AI Thinks This" -- a full, per-engine breakdown of the current
prediction: for each of Technical Analysis/News/On-chain/Whales/Macro/
Sentiment/Correlations/Pattern/Historical Patterns, a Signal (direction), a
Confidence (0-100), a Weight (this engine's share of the final vote), and
an Explanation (real evidence text) -- so the final prediction is fully
traceable back to the real numbers behind it. A final `summary_text`
narrates all of the above into one plain-language paragraph.

Composes entirely from data other engines already computed, following the
exact reuse pattern established by ForecastEngine/ExecutiveSummaryEngine:

- Signal/Weight/Explanation for Technical Analysis, News, Sentiment, Macro,
  Whales, Pattern, and Historical Patterns come straight off the latest
  `WatchdogSnapshot.consensus` (the same persisted Consensus vote tally
  Forecast Center and Executive Summary already read, now covering all
  seven of these as real dedicated agents in `AgentOrchestrator`) -- no
  re-invoking the agent orchestrator. On-chain and Correlations have no
  dedicated agent vote (both are honestly always-unavailable or
  no-directional-signal today, see `OnchainAgent`/`CorrelationAgent`), so
  Weight stays `None` for them.
- Confidence for every row reuses each row's own richer, pre-existing
  derivation (`ForecastEngine`'s `_confidence_breakdown()` formulas for
  Technical/News/Sentiment/Macro/Whales/On-chain/Correlations, PatternAgent's
  recency-weighted agreement for Pattern, the historical analogs' average
  similarity for Historical Patterns) rather than the consensus tally,
  which only stores vote weight, not per-agent confidence. Macro's
  confidence is corrected to read `GlobalScoreEngine.macro_pressure_score`
  (a genuine macro-specific number) rather than the whole-market
  `WatchdogSnapshot.confidence_score` Forecast Center's row happens to use.
- On-chain is honestly reported unavailable (with the real reason string)
  -- `OnChainIntelligenceEngine` is a documented no-data-source scaffold.
- `ExplanationEngine.build()` is called once, unmodified, for the
  historical-examples data and folded into the response alongside the new
  `engine_breakdown` -- this module adds to that dict, it does not
  duplicate any of its computation.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import WatchdogSnapshot
from app.services.agents.pattern_agent import _recency_weighted_direction
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
from app.services.history.registry import find_symbol_config
from app.services.history.schemas import Timeframe
from app.services.onchain.engine import OnChainIntelligenceEngine
from app.services.patterns.engine import PatternEngine
from app.services.sentiment.engine import SentimentEngine
from app.services.technical.engine import TechnicalAnalysisEngine
from app.services.whales.engine import WhaleIntelligenceEngine

# Consensus agent keys (app/services/agents/*.py) that map 1:1 onto a
# requested category -- reused to pull that agent's real bullish/bearish/
# neutral bucket, evidence excerpt, and vote-weight share straight off
# WatchdogSnapshot.consensus, never re-derived. Whale/Pattern/Historical are
# now real dedicated consensus voters too (see AgentOrchestrator), so their
# Signal/Weight come from the same real vote tally as Technical/News/
# Sentiment/Macro -- Confidence still uses each row's own richer, pre-existing
# derivation (whale positioning distance, pattern recency-weighted agreement,
# historical analog similarity) since the consensus tally only stores vote
# weight, not per-agent confidence.
_CATEGORY_AGENT_KEYS: dict[str, str] = {
    "Technical Analysis": "technical",
    "News": "news",
    "Sentiment": "sentiment",
    "Macro": "macro",
    "Whales": "whale",
    "Pattern": "pattern",
    "Historical Patterns": "historical",
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


def _pattern_explanation(signals: list) -> str | None:
    """Pure function: real detected patterns, most recent first -- the same
    rows PatternAgent's own consensus vote is built from, quoted here for
    the Explanation column instead of collapsed into a vote."""
    if not signals:
        return "No patterns detected in recent history."
    parts = [f"{s.pattern_name} ({s.direction}) at {s.timestamp.date()}" for s in signals[:3]]
    return ", ".join(parts)


def _compose_summary_text(
    final_bias: str | None, consensus: dict | None, rows: list[EngineBreakdownRow]
) -> str:
    """Pure function: one final paragraph summarizing every row above --
    not a new judgment, just plain-language composition over numbers this
    module already computed (how many engines actually reported a read,
    which one carries the most weight, what its own evidence says). None of
    the inputs are re-derived; this only narrates them."""
    available = [r for r in rows if r.signal is not None]
    if not available or consensus is None:
        return "Not enough engines reported a signal this cycle to form a consensus view."

    agreement_score = consensus.get("agreement_score")
    strongest_name = None
    strongest_weight = -1.0
    for row in available:
        if row.weight is not None and row.weight > strongest_weight:
            strongest_weight = row.weight
            strongest_name = row.name

    sentence = (
        f"{len(available)} of {len(rows)} engines reported a signal this cycle; "
        f"the overall read is {final_bias or 'Neutral'}"
    )
    if agreement_score is not None:
        sentence += f" with {agreement_score}% agreement"
    sentence += "."
    if strongest_name is not None:
        strongest_row = next(r for r in available if r.name == strongest_name)
        sentence += f" {strongest_name} carries the most weight ({strongest_weight}%)"
        if strongest_row.explanation:
            sentence += f": {strongest_row.explanation}"
        sentence += "."
    return sentence


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
        pattern_engine: PatternEngine,
    ) -> None:
        self._session_factory = session_factory
        self._explanation_engine = explanation_engine
        self._global_score_engine = global_score_engine
        self._technical_engine = technical_engine
        self._sentiment_engine = sentiment_engine
        self._correlation_engine = correlation_engine
        self._whale_engine = whale_engine
        self._onchain_engine = onchain_engine
        self._pattern_engine = pattern_engine

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
        config = find_symbol_config(symbol)
        pattern_signals = (
            await self._pattern_engine.get_latest(
                config.symbol, timeframe=Timeframe.DAILY, limit=10
            )
            if config is not None
            else []
        )

        consensus = watchdog.consensus if watchdog is not None else None

        def _agent_row(
            name: str, confidence: int | None, explanation_text: str | None = None
        ) -> EngineBreakdownRow:
            agent_key = _CATEGORY_AGENT_KEYS[name]
            return EngineBreakdownRow(
                name=name,
                signal=_agent_signal(agent_key, consensus),
                confidence=confidence,
                weight=_agent_weight(agent_key, consensus),
                explanation=(
                    explanation_text
                    if explanation_text is not None
                    else _agent_explanation(agent_key, consensus)
                ),
            )

        macro_confidence = (
            _distance_from_neutral(global_score.macro_pressure_score)
            if global_score is not None
            else None
        )
        _, historical_explanation = _historical_signal_and_explanation(
            explanation.get("historical_examples") or []
        )
        _, pattern_confidence = _recency_weighted_direction(pattern_signals)

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
            _agent_row(
                "Whales", _whale_confidence(whale_snapshot), _whale_explanation(whale_snapshot)
            ),
            EngineBreakdownRow(
                name="Correlations",
                signal=None,
                confidence=_correlation_confidence(correlations, symbol),
                weight=None,
                explanation=_correlation_explanation(correlations, symbol),
            ),
            _agent_row("Pattern", pattern_confidence, _pattern_explanation(pattern_signals)),
            _agent_row(
                "Historical Patterns",
                _historical_confidence(explanation.get("historical_examples") or []),
                historical_explanation,
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
        explanation["summary_text"] = _compose_summary_text(final_bias, consensus, rows)
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
        PatternEngine(session_factory),
    )
