import json
import logging
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.database.models import (
    AssetPrice,
    Correlation,
    CryptoHistory,
    GlobalMarketScore,
    MarketRegimeSnapshot,
    NewsItem,
    Report,
    SignalSnapshot,
)
from app.llm.client import generate_analysis_json
from app.services.agents.base import AgentOutput
from app.services.agents.orchestrator import AgentOrchestrator, build_agent_orchestrator
from app.services.analysis.correlation import CorrelationEngine
from app.services.analysis.regime import MarketRegime, RegimeDetector
from app.services.analysis.schemas import AIAnalysisContent
from app.services.common.formatting import format_asset_lines
from app.services.consensus.engine import compute_consensus
from app.services.etf.engine import ETFIntelligenceEngine
from app.services.global_score.engine import GlobalScoreEngine
from app.services.history.schemas import Timeframe
from app.services.knowledge.engine import build_grounding_text
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.portfolio.advisor import PortfolioAdvisorEngine
from app.services.portfolio.engine import PortfolioEngine
from app.services.probability.engine import ProbabilityEngine
from app.services.ranking.engine import RankingEngine
from app.services.reliability.engine import AgentReliabilityEngine
from app.services.scenarios.engine import compute_scenarios, scenario_extremes
from app.services.signals.engine import SignalEngine
from app.services.similar_market.engine import SimilarMarketEngine
from app.services.whales.engine import WhaleIntelligenceEngine

logger = logging.getLogger(__name__)

# Symbols worth summarizing in every report, in display order.
_KEY_SYMBOLS: tuple[str, ...] = (
    "BTC",
    "ETH",
    "SOL",
    "TOTAL",
    "BTC.D",
    "NASDAQ",
    "SPX",
    "DJI",
    "RUT",
    "DXY",
    "GOLD",
    "SILVER",
    "OIL",
    "VIX",
    "US10Y",
    "US30Y",
    "FEDRATE",
)

_HIGH_RISK_REGIMES = frozenset(
    {
        MarketRegime.RISK_OFF,
        MarketRegime.FLIGHT_TO_SAFETY,
        MarketRegime.LIQUIDITY_CONTRACTION,
        MarketRegime.BEAR,
        MarketRegime.CAPITULATION,
        MarketRegime.DISTRIBUTION,
    }
)
_LOW_RISK_REGIMES = frozenset(
    {
        MarketRegime.RISK_ON,
        MarketRegime.LIQUIDITY_EXPANSION,
        MarketRegime.BULL,
        MarketRegime.RECOVERY,
        MarketRegime.ACCUMULATION,
        MarketRegime.STRONG_BULL,
    }
)

SYSTEM_PROMPT = """You are a senior macro and crypto market analyst, in the style of a \
Bloomberg Terminal / Glassnode / institutional research desk. You are given real, \
already-computed market data, recent news, asset correlations, a detected market regime, \
and a bull/bear signal score.

Your job is to explain WHY markets are moving -- never simply state that an asset went up \
or down. Ground every claim in the data provided below. If a section's underlying data is \
unavailable, say so explicitly (e.g. "US Treasury yield data was unavailable this cycle") \
rather than inventing detail.

For "historical_comparison" specifically: base it on the HISTORICAL ANALOGS section below, \
which lists real past dates with similar technical conditions and what actually happened \
next. Reference those real dates and outcomes rather than a generic or invented comparison. \
If no analogs are available, say so explicitly.

For "liquidity_and_risk": ground it in the GLOBAL MARKET SCORE section (liquidity, fear/greed, \
risk-on/off sub-scores) -- explain what those already-computed numbers mean, don't recompute \
or contradict them. For "institutional_behavior": also incorporate the ETF FLOW PROXY and \
WHALE ACTIVITY sections; if either says data is unavailable, say so plainly instead of \
guessing. "scenarios" should describe 2-3 concrete near-term paths (not just bull/bear labels) \
consistent with the probability split. "actionable_insights" should be practical and specific \
to what changed today, not generic trading advice.

You are also given a MULTI-AGENT SUMMARIES section: independent read-outs already produced by \
a Macro Agent, a Crypto Agent, an Equity Agent, a News Agent and a Sentiment Agent. You are the \
Reasoning Agent -- your job is to synthesize their outputs into one coherent narrative, not to \
just concatenate or restate them. Where two agents disagree (e.g. macro liquidity improving \
while crypto whale data shows distribution), call that tension out explicitly in "why" or \
"main_risks" rather than smoothing it over.

Respond with a single JSON object with exactly these fields (all strings except the three \
probability fields, which are integers 0-100 that must sum to 100):
{
  "what_changed": "...",
  "why": "...",
  "who_is_driving": "...",
  "institutional_behavior": "...",
  "macro_explanation": "...",
  "historical_comparison": "...",
  "liquidity_and_risk": "...",
  "main_risks": "...",
  "key_events_today": "...",
  "scenarios": "...",
  "actionable_insights": "...",
  "probability_bullish_pct": 0,
  "probability_bearish_pct": 0,
  "probability_neutral_pct": 0
}"""


def derive_risk_level(regime: MarketRegime) -> str:
    if regime in _HIGH_RISK_REGIMES:
        return "high"
    if regime in _LOW_RISK_REGIMES:
        return "low"
    return "moderate"


_STRING_FIELD_PLACEHOLDER = (
    "Not available this cycle -- the AI model returned an invalid value for this field."
)
_PROBABILITY_FIELD_PLACEHOLDER = 0


def recover_analysis_fields(raw: dict, exc: ValidationError) -> tuple[dict, list[str]]:
    """One or more AIAnalysisContent fields failed validation (wrong type,
    an out-of-range percentage, or a missing key) -- rather than discarding
    an otherwise-valid report, substitutes an honest placeholder for exactly
    the fields `exc` names and leaves every other field's real LLM content
    untouched. Returns the recovered dict plus the sorted list of field
    names that needed a placeholder (empty if none did)."""
    failed_fields = sorted({str(err["loc"][0]) for err in exc.errors() if err["loc"]})
    recovered = dict(raw)
    for name in failed_fields:
        recovered[name] = (
            _PROBABILITY_FIELD_PLACEHOLDER
            if name.startswith("probability_")
            else _STRING_FIELD_PLACEHOLDER
        )
    return recovered, failed_fields


def _format_replay_comparison(replay_comparison: dict | None) -> str | None:
    """v9.0 "Reports should reference Replay" -- turns a
    get_replay_comparison() dict into a one-line addendum for Historical
    Comparison. Genuinely different content from the LLM's own narrative
    (which grounds in technical/price analogs): this is a real regime/
    health/risk delta Replay already computed, not a restatement."""
    if replay_comparison is None:
        return None
    diff = replay_comparison["diff"]
    hours_ago = replay_comparison["hours_ago"]
    parts = []
    if diff["regime"]["changed"]:
        parts.append(f"regime shifted {diff['regime']['from']} -> {diff['regime']['to']}")
    for field, label in (("health_score", "health"), ("risk_score", "risk")):
        entry = diff[field]
        if entry["delta"]:
            parts.append(f"{label} {entry['delta']:+d}")
    if not parts:
        return f"No material change vs. {hours_ago}h ago (Replay)."
    return f"Vs. {hours_ago}h ago (Replay): " + "; ".join(parts) + "."


def _format_watchdog_citation(watchdog: dict | None) -> str | None:
    """v12.0 P2 "Add Watchdog citation to Reports" -- Watchdog runs its own
    5-agent Investment Committee vote on its own scheduled cycle
    (WatchdogSnapshot.market_health/committee_recommendation), but the
    institutional report never referenced it: the report's own agent run
    only tallies a raw Consensus score, it never convenes a full Committee
    vote of its own. This is a read-only citation of Watchdog's last cycle
    (explicitly labeled as such, since it runs on its own schedule, not
    this report's), not a second Committee vote -- and deliberately never
    cites Watchdog's highest_risk/biggest_opportunity, since those are
    scenario_extremes() over the same Scenario Engine snapshot this report
    already reads above; citing them here would restate the same number
    under a different label, not add new information.
    """
    if not watchdog or not watchdog.get("committee_recommendation"):
        return None
    return (
        f"Watchdog's last cycle reads {watchdog['market_health']} -- "
        f"Investment Committee: {watchdog['committee_recommendation']}."
    )


def _format_data_quality_note(recovered_fields: list | None) -> str | None:
    """v12.0 P2 "Report Generator partial-recovery for LLM field failures" --
    generate_and_store() no longer discards an entire report when only some
    of the LLM's fields fail validation (recover_analysis_fields()
    substitutes an honest placeholder for just those fields and keeps every
    other field's real content). This surfaces that substitution instead of
    silently presenting a placeholder string as if it were genuine analysis."""
    if not recovered_fields:
        return None
    return (
        f"Data quality note: {len(recovered_fields)} narrative field(s) "
        f"({', '.join(recovered_fields)}) came back invalid from the AI model this cycle "
        "and were replaced with a placeholder; every other field is the model's real output."
    )


def watchdog_report_input(watchdog_snapshot) -> dict | None:
    """Shapes a WatchdogSnapshot row into the small dict
    build_institutional_report()/_format_watchdog_citation() need -- shared
    by every call site (API, Telegram, scheduled broadcast) so the field
    list lives in one place."""
    if watchdog_snapshot is None:
        return None
    return {
        "market_health": watchdog_snapshot.market_health,
        "committee_recommendation": watchdog_snapshot.committee_recommendation,
    }


def _format_risk_detail(global_score: dict | None) -> str | None:
    """v12.0 "Reports should reference Risk Engine detail" -- GlobalScoreEngine
    already computes risk-on/risk-off/liquidity/macro-pressure sub-scores for
    this exact report cycle (stored in report.institutional_summary
    ['global_score'] by generate_and_store(), see _format_global_score_lines()
    which already renders these same fields for the LLM prompt) but
    build_institutional_report() never surfaced them as their own field --
    the institutional report only ever showed the LLM's narrative main_risks
    text. Read-only composition of an already-computed dict, not a second
    calculation."""
    if not global_score:
        return None
    return (
        f"Risk-On {global_score['risk_on_score']} / Risk-Off {global_score['risk_off_score']} | "
        f"Liquidity {global_score['liquidity_score']} | "
        f"Macro pressure {global_score['macro_pressure_score']}"
    )


def build_institutional_report(
    report: Report,
    sector_breadth: list[dict] | None = None,
    replay_comparison: dict | None = None,
    watchdog: dict | None = None,
) -> dict:
    """Restructures a persisted Report into the institutional-research shape
    v8.0 calls for -- Executive Summary, Biggest Opportunity, Biggest Risk,
    Market Drivers, Sector Rotation, Historical Comparison, AI Conclusion,
    What to Watch Next. Every field is a direct read or template composition
    of report.analysis/report.institutional_summary (both already produced
    by generate_and_store()) plus, for sector rotation, the Market Scanner's
    already-computed sector breadth, for historical comparison, Replay's
    own regime/health/risk delta (get_replay_comparison()), and for the
    Watchdog citation, WatchdogEngine's own last-cycle snapshot -- no new
    LLM call, no fabricated figures, no second computation of anything
    Scenario Engine already did.
    """
    analysis = report.analysis
    scenarios = (report.institutional_summary or {}).get("scenarios")
    _, _, highest_risk, biggest_opportunity = scenario_extremes(scenarios)

    # v9.0 noise pass: the regime/risk/bull-bear/confidence numbers are
    # already shown as their own header fields everywhere this is rendered
    # (Telegram's report header lines, the dashboard's report cards) --
    # restating them as a sentence prefix here duplicated that, so the
    # summary is just the LLM's real narrative of what changed.
    executive_summary = analysis.get("what_changed", "").strip()

    market_drivers = (
        " ".join(
            part
            for part in (analysis.get("who_is_driving"), analysis.get("macro_explanation"))
            if part
        )
        or "n/a"
    )

    if sector_breadth:
        ranked = [s for s in sector_breadth if s.get("avg_change_pct_24h") is not None]
        leaders = ranked[:3]
        laggards = ranked[-3:] if len(ranked) > 3 else []
        leader_str = ", ".join(f"{s['sector']} ({s['avg_change_pct_24h']:+.2f}%)" for s in leaders)
        laggard_str = ", ".join(
            f"{s['sector']} ({s['avg_change_pct_24h']:+.2f}%)" for s in laggards
        )
        sector_rotation = f"Leading: {leader_str or 'n/a'}. Lagging: {laggard_str or 'n/a'}."
    else:
        sector_rotation = (
            "Sector breadth unavailable -- the Market Scanner has not completed a cycle yet."
        )

    historical_comparison = analysis.get("historical_comparison", "n/a")
    replay_note = _format_replay_comparison(replay_comparison)
    if replay_note:
        historical_comparison = f"{historical_comparison} {replay_note}"

    risk_detail = _format_risk_detail((report.institutional_summary or {}).get("global_score"))
    watchdog_note = _format_watchdog_citation(watchdog)
    data_quality_note = _format_data_quality_note(
        (report.institutional_summary or {}).get("analysis_recovered_fields")
    )

    return {
        "executive_summary": executive_summary or "No summary available.",
        "biggest_opportunity": biggest_opportunity or "No bullish scenario currently dominant.",
        "biggest_risk": highest_risk or "No bearish scenario currently dominant.",
        "risk_detail": risk_detail,
        "watchdog_note": watchdog_note,
        "data_quality_note": data_quality_note,
        "main_risks": analysis.get("main_risks", "n/a"),
        "market_drivers": market_drivers,
        "institutional_behavior": analysis.get("institutional_behavior", "n/a"),
        "sector_rotation": sector_rotation,
        "historical_comparison": historical_comparison,
        "ai_conclusion": analysis.get("actionable_insights", "n/a"),
        "what_to_watch_next": analysis.get("key_events_today", "n/a"),
    }


def strip_json_fence(text: str) -> str:
    """Strips a wrapping ```json / ``` markdown code fence, if present.

    Anthropic has no forced-JSON response mode (unlike OpenAI's
    `response_format: json_object`, used for the OpenAI path), so Claude
    routinely wraps its JSON answer in a markdown fence despite being asked
    for a bare JSON object -- left unstripped, that leading backtick makes
    json.loads() fail immediately with a misleading "Expecting value: line
    1 column 1 (char 0)". Only strips the opening fence line unconditionally
    (a response truncated by max_tokens won't have a closing fence to
    strip), so a genuinely truncated response still fails json.loads() with
    an accurate error instead of being silently misinterpreted as empty.
    """
    text = text.strip()
    if not text.startswith("```"):
        return text
    first_newline = text.find("\n")
    if first_newline == -1:
        return text
    text = text[first_newline + 1 :]
    if text.rstrip().endswith("```"):
        text = text.rstrip()[:-3]
    return text.strip()


def _format_market_lines(assets: list[AssetPrice]) -> list[str]:
    return format_asset_lines(assets, _KEY_SYMBOLS)


def _format_news_lines(news: list[NewsItem]) -> list[str]:
    if not news:
        return ["- No recent news available."]
    return [
        f"- [{item.category.value}] ({item.sentiment.value}) {item.title} -- {item.source}"
        for item in news
    ]


def _format_correlation_lines(correlations: list[Correlation]) -> list[str]:
    if not correlations:
        return ["- No correlation data available yet."]
    return [
        f"- {c.symbol_a}/{c.symbol_b} ({c.window_days}d): {float(c.correlation):+.2f}"
        for c in correlations
    ]


def _serialize_global_score(row: GlobalMarketScore | None) -> dict | None:
    if row is None:
        return None
    return {
        "risk_on_score": row.risk_on_score,
        "risk_off_score": row.risk_off_score,
        "liquidity_score": row.liquidity_score,
        "fear_score": row.fear_score,
        "greed_score": row.greed_score,
        "macro_pressure_score": row.macro_pressure_score,
        "institutional_activity_score": row.institutional_activity_score,
        "crypto_strength_score": row.crypto_strength_score,
        "stock_strength_score": row.stock_strength_score,
        "global_score": row.global_score,
        "trend_strength_score": row.trend_strength_score,
        "risk_score": row.risk_score,
        "confidence_score": row.confidence_score,
    }


def _format_global_score_lines(global_score: dict | None) -> list[str]:
    if global_score is None:
        return ["- Not yet computed."]
    trend_strength = global_score.get("trend_strength_score")
    risk_score = global_score.get("risk_score")
    confidence_score = global_score.get("confidence_score")
    return [
        f"- Global score: {global_score['global_score']}/100",
        f"- Risk-On {global_score['risk_on_score']} / Risk-Off {global_score['risk_off_score']}",
        f"- Liquidity {global_score['liquidity_score']}",
        f"- Fear {global_score['fear_score']} / Greed {global_score['greed_score']}",
        f"- Macro pressure {global_score['macro_pressure_score']}",
        f"- Institutional activity {global_score['institutional_activity_score']}",
        f"- Crypto strength {global_score['crypto_strength_score']}",
        f"- Stock strength {global_score['stock_strength_score']}",
        f"- Trend strength {trend_strength if trend_strength is not None else 'unavailable'}",
        f"- Risk score {risk_score if risk_score is not None else 'unavailable'}",
        f"- Confidence score {confidence_score if confidence_score is not None else 'unavailable'}",
    ]


def _format_etf_proxy_lines(etf_proxy: dict | None) -> list[str]:
    if etf_proxy is None or not etf_proxy.get("available"):
        reason = (etf_proxy or {}).get("reason", "Not available.")
        return [f"- {reason}"]
    return [
        "- Proxy only (news sentiment, not confirmed dollar flows):",
        f"- Classification: {etf_proxy['classification']}",
        (
            f"- {etf_proxy['bullish_items']} bullish / {etf_proxy['bearish_items']} bearish / "
            f"{etf_proxy['neutral_items']} neutral ETF-category items in the last "
            f"{etf_proxy['window_hours']}h"
        ),
    ]


def _format_whale_lines(whale_snapshot: dict | None) -> list[str]:
    if whale_snapshot is None or not whale_snapshot.get("available"):
        reason = (whale_snapshot or {}).get("reason", "Not available.")
        return [f"- {reason}"]
    return [f"- {k}: {v}" for k, v in whale_snapshot.items() if k not in ("available", "symbol")]


def _format_agent_summaries(agent_outputs: dict[str, AgentOutput] | None) -> str:
    if not agent_outputs:
        return "- Not yet computed."
    return "\n\n".join(output.summary for output in agent_outputs.values())


def build_user_prompt(
    assets: list[AssetPrice],
    news: list[NewsItem],
    correlations: list[Correlation],
    regime_snapshot: MarketRegimeSnapshot,
    signal_snapshot: SignalSnapshot,
    historical_grounding: str = "- Historical analog data unavailable.",
    global_score: dict | None = None,
    etf_proxy: dict | None = None,
    whale_snapshot: dict | None = None,
    agent_outputs: dict[str, AgentOutput] | None = None,
) -> str:
    """Builds the LLM user prompt from already-computed, real data. Pure and unit-testable."""
    return "\n\n".join(
        [
            "MULTI-AGENT SUMMARIES (Macro / Crypto / Equity / News / Sentiment agents)",
            _format_agent_summaries(agent_outputs),
            "MARKET SNAPSHOT",
            "\n".join(_format_market_lines(assets)),
            "DETECTED MARKET REGIME",
            f"- Regime: {regime_snapshot.regime.value}",
            f"- Inputs: {json.dumps(regime_snapshot.inputs)}",
            "BULL/BEAR SIGNAL SCORE",
            (
                f"- Bull score: {signal_snapshot.bull_score}, "
                f"Bear score: {signal_snapshot.bear_score}, "
                f"Net: {signal_snapshot.net_score}, "
                f"Confidence: {signal_snapshot.confidence_pct}%"
            ),
            f"- Factor breakdown: {json.dumps(signal_snapshot.factors)}",
            "GLOBAL MARKET SCORE",
            "\n".join(_format_global_score_lines(global_score)),
            "ROLLING CORRELATIONS",
            "\n".join(_format_correlation_lines(correlations)),
            "HISTORICAL ANALOGS (real past episodes with similar technical conditions)",
            historical_grounding,
            "ETF FLOW PROXY",
            "\n".join(_format_etf_proxy_lines(etf_proxy)),
            "WHALE ACTIVITY",
            "\n".join(_format_whale_lines(whale_snapshot)),
            "RECENT NEWS (most recent first)",
            "\n".join(_format_news_lines(news)),
        ]
    )


class ReportGenerator:
    """Gathers every analysis engine's latest output and asks the LLM to explain WHY."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        market_repository: MarketRepository,
        news_repository: NewsRepository,
        correlation_engine: CorrelationEngine,
        regime_detector: RegimeDetector,
        signal_engine: SignalEngine,
        similar_market_engine: SimilarMarketEngine | None = None,
        global_score_engine: GlobalScoreEngine | None = None,
        etf_engine: ETFIntelligenceEngine | None = None,
        whale_engine: WhaleIntelligenceEngine | None = None,
        agent_orchestrator: AgentOrchestrator | None = None,
        portfolio_advisor: PortfolioAdvisorEngine | None = None,
        reliability_engine: AgentReliabilityEngine | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._market_repository = market_repository
        self._news_repository = news_repository
        self._correlation_engine = correlation_engine
        self._regime_detector = regime_detector
        self._signal_engine = signal_engine
        self._similar_market_engine = similar_market_engine or SimilarMarketEngine(session_factory)
        self._global_score_engine = global_score_engine or GlobalScoreEngine(
            session_factory, market_repository, regime_detector, signal_engine
        )
        self._etf_engine = etf_engine or ETFIntelligenceEngine(news_repository)
        self._whale_engine = whale_engine or WhaleIntelligenceEngine()
        self._agent_orchestrator = agent_orchestrator or build_agent_orchestrator()
        self._portfolio_advisor = portfolio_advisor or PortfolioAdvisorEngine(
            session_factory,
            signal_engine,
            ProbabilityEngine(session_factory),
            PortfolioEngine(session_factory, market_repository),
            RankingEngine(session_factory),
        )
        self._reliability_engine = reliability_engine or AgentReliabilityEngine(session_factory)

    async def _safe_reliability(self, regime: str | None = None) -> dict[str, float] | None:
        """Forecast Intelligence Upgrade -- Regime-Aware Weighting: same
        pattern as WatchdogEngine._safe_reliability() -- the report's own
        Consensus tally (institutional_summary["consensus"]) previously
        weighted every agent by raw confidence only, with no reliability
        input at all. An agent's weight is now scaled by its own historical
        accuracy IN THIS REGIME when one is available, falling back to the
        flat regime-blind accuracy otherwise."""
        try:
            if regime is None:
                return await self._reliability_engine.evaluate_reliability()
            hierarchical = await self._reliability_engine.evaluate_reliability_hierarchical(
                regime=regime
            )
            return {
                agent: result["accuracy_pct"]
                for agent, result in hierarchical.items()
                if result.get("accuracy_pct") is not None
            }
        except Exception:
            return None

    async def generate_and_store(self, report_type: str = "scheduled") -> Report:
        assets = await self._market_repository.get_latest()
        news = await self._news_repository.get_recent(limit=15)
        correlations = await self._correlation_engine.get_latest()
        regime_snapshot = await self._regime_detector.get_latest()
        signal_snapshot = await self._signal_engine.get_latest()

        if regime_snapshot is None or signal_snapshot is None:
            raise RuntimeError(
                "Cannot generate a report before regime detection and signal scoring "
                "have run at least once"
            )

        try:
            similar_matches = await self._similar_market_engine.find_similar_periods(
                "BTC", CryptoHistory, Timeframe.DAILY, k=5, include_nearby_events=True
            )
        except Exception:
            logger.warning("Similar market lookup failed; continuing without it", exc_info=True)
            similar_matches = []
        historical_grounding = build_grounding_text("BTC", similar_matches)

        global_score_row = await self._global_score_engine.compute_and_store()
        global_score = _serialize_global_score(global_score_row)
        etf_proxy = await self._etf_engine.get_flow_proxy()
        whale_snapshot = await self._whale_engine.get_snapshot("BTC")

        try:
            agent_outputs = await self._agent_orchestrator.run_all()
        except Exception:
            logger.warning("Agent orchestrator failed; continuing without it", exc_info=True)
            agent_outputs = None

        # Consensus and Scenarios are pure functions over data already fetched
        # this cycle (agent_outputs, global_score_row) -- no second agent run,
        # no second Global Score computation.
        live_regime = regime_snapshot.regime.value if regime_snapshot is not None else None
        reliability = await self._safe_reliability(live_regime) if agent_outputs else None
        consensus_result = compute_consensus(agent_outputs, reliability) if agent_outputs else None
        scenarios = compute_scenarios(global_score_row) if global_score_row is not None else None

        try:
            portfolio_advice = await self._portfolio_advisor.advise("BTC", Timeframe.DAILY)
        except Exception:
            logger.warning("Portfolio advisor failed; continuing without it", exc_info=True)
            portfolio_advice = None

        user_prompt = build_user_prompt(
            assets,
            news,
            correlations,
            regime_snapshot,
            signal_snapshot,
            historical_grounding,
            global_score,
            etf_proxy,
            whale_snapshot,
            agent_outputs,
        )

        raw_content = await generate_analysis_json(SYSTEM_PROMPT, user_prompt)

        try:
            parsed_content = json.loads(strip_json_fence(raw_content))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"LLM returned an invalid analysis payload: {exc}") from exc

        recovered_fields: list[str] = []
        try:
            analysis = AIAnalysisContent.model_validate(parsed_content)
        except ValidationError as exc:
            if not isinstance(parsed_content, dict):
                raise RuntimeError(f"LLM returned an invalid analysis payload: {exc}") from exc
            recovered_content, recovered_fields = recover_analysis_fields(parsed_content, exc)
            logger.warning(
                "LLM analysis had invalid fields %s; substituting honest placeholders "
                "and continuing report generation",
                recovered_fields,
            )
            try:
                analysis = AIAnalysisContent.model_validate(recovered_content)
            except ValidationError as exc2:
                raise RuntimeError(f"LLM returned an invalid analysis payload: {exc2}") from exc2

        market_summary: dict[str, Any] = {
            a.symbol: {
                "price": float(a.price),
                "change_pct_24h": float(a.change_pct_24h) if a.change_pct_24h is not None else None,
            }
            for a in assets
            if a.symbol in _KEY_SYMBOLS
        }
        correlations_summary = [
            {
                "pair": f"{c.symbol_a}/{c.symbol_b}",
                "window_days": c.window_days,
                "correlation": float(c.correlation),
            }
            for c in correlations
        ]

        report = Report(
            id=uuid.uuid4(),
            report_type=report_type,
            regime=regime_snapshot.regime.value,
            risk_level=derive_risk_level(regime_snapshot.regime),
            bull_score=signal_snapshot.bull_score,
            bear_score=signal_snapshot.bear_score,
            confidence_pct=signal_snapshot.confidence_pct,
            market_summary=market_summary,
            correlations_summary=correlations_summary,
            institutional_summary={
                "global_score": global_score,
                "etf_flow_proxy": etf_proxy,
                "whale_activity": whale_snapshot,
                "agents": (
                    {name: output.to_dict() for name, output in agent_outputs.items()}
                    if agent_outputs
                    else None
                ),
                "consensus": consensus_result.to_dict() if consensus_result else None,
                "scenarios": scenarios,
                "portfolio_advice": portfolio_advice.to_dict() if portfolio_advice else None,
                "analysis_recovered_fields": recovered_fields or None,
            },
            analysis=analysis.model_dump(),
        )

        async with self._session_factory() as session:
            session.add(report)
            await session.commit()
            await session.refresh(report)
        return report

    async def get_latest(self) -> Report | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(Report).order_by(Report.generated_at.desc()).limit(1)
            )
