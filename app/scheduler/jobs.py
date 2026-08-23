import functools
import logging
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.api.reports import build_report_generator
from app.config import get_settings
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.agents.orchestrator import build_agent_orchestrator
from app.services.alert_performance.engine import grade_alert_performance
from app.services.alerts.engine import build_alert_engine
from app.services.alerts.rules import build_alert_rule_engine
from app.services.analysis.correlation import CorrelationEngine
from app.services.analysis.regime import RegimeDetector
from app.services.analysis.report import build_institutional_report, watchdog_report_input
from app.services.breakout.engine import BreakoutEngine
from app.services.calendar.engine import EconomicCalendarEngine
from app.services.committee.engine import CommitteeEngine
from app.services.etf.engine import ETFIntelligenceEngine
from app.services.features.engine import FeatureEngine
from app.services.forecast.engine import (
    HORIZONS,
    build_forecast_engine,
    check_and_invalidate_forecasts,
    grade_price_forecasts,
)
from app.services.global_score.engine import GlobalScoreEngine
from app.services.history.pipeline import run_sync
from app.services.history.registry import build_registry, find_symbol_config
from app.services.history.schemas import Timeframe
from app.services.hypothesis.engine import HypothesisEngine
from app.services.market.aggregator import MarketDataAggregator
from app.services.market.repository import MarketRepository
from app.services.news.aggregator import NewsAggregator
from app.services.news.repository import NewsRepository
from app.services.portfolio.advisor import PortfolioAdvisorEngine
from app.services.portfolio.engine import PortfolioEngine
from app.services.probability.engine import ProbabilityEngine
from app.services.ranking.engine import RankingEngine
from app.services.realtime.config import parse_watchlist
from app.services.reliability.engine import AgentReliabilityEngine
from app.services.replay.engine import MarketReplayEngine, get_replay_comparison
from app.services.research.researcher import AIResearcherEngine
from app.services.scanner.engine import build_market_scanner_engine
from app.services.scanner.notifier import send_scanner_notifications
from app.services.scenarios.engine import ScenarioEngine
from app.services.sentiment.engine import SentimentEngine
from app.services.shocks.engine import build_critical_alert_engine
from app.services.signals.engine import SignalEngine
from app.services.technical.engine import build_technical_analysis_engine
from app.services.terminal.engine import TerminalEngine
from app.services.watchdog.engine import build_watchdog_engine
from app.services.watchdog.provider_health import record_provider_failure, record_provider_success
from app.services.whales.engine import WhaleIntelligenceEngine
from app.telegram.broadcast import broadcast_report, broadcast_text
from app.telegram.formatters import format_monthly_performance, format_weekly_review

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

MARKET_DATA_JOB_ID = "collect_market_data"
CRYPTO_HISTORY_SYNC_JOB_ID = "sync_crypto_daily_history"
NEWS_JOB_ID = "collect_news"
CORRELATION_JOB_ID = "compute_correlations"
REGIME_JOB_ID = "detect_regime"
SIGNAL_JOB_ID = "compute_signals"
GLOBAL_SCORE_JOB_ID = "compute_global_score"
SENTIMENT_JOB_ID = "compute_sentiment"
SCENARIO_JOB_ID = "compute_scenarios"
WHALE_ETF_SNAPSHOT_JOB_ID = "snapshot_whale_etf"
ALERT_CHECK_JOB_ID = "check_alerts"
ALERT_RULE_CHECK_JOB_ID = "check_alert_rules"
CRITICAL_ALERT_CHECK_JOB_ID = "check_critical_alerts"
TECHNICAL_ANALYSIS_JOB_ID = "compute_technical_analysis"
WATCHDOG_SNAPSHOT_JOB_ID = "compute_watchdog_snapshot"
MARKET_SCAN_JOB_ID = "compute_market_scan"

# BTC/ETH/SOL (crypto) plus the most-watched indices/macro symbols already
# in the history sync registry -- see app/services/technical/provider.py
# for exactly why this list can't cover the mission's full asset list
# without a configured TradingView MCP endpoint.
TECHNICAL_ANALYSIS_SYMBOLS: tuple[str, ...] = (
    "BTC",
    "ETH",
    "SOL",
    "SPX",
    "NASDAQ",
    "DJI",
    "DXY",
    "GOLD",
    "VIX",
)
REPORT_JOB_ID = "generate_scheduled_report"
ECONOMIC_CALENDAR_JOB_ID = "sync_economic_calendar"
FEATURE_JOB_ID = "compute_features"
AI_RESEARCHER_JOB_ID = "generate_research_note"
HYPOTHESIS_JOB_ID = "test_hypotheses"
RANKING_JOB_ID = "compute_ranking"
REPLAY_JOB_ID = "compute_market_replay"
BREAKOUT_JOB_ID = "compute_breakout_intelligence"
WEEKLY_REVIEW_JOB_ID = "broadcast_weekly_review"
MONTHLY_PERFORMANCE_JOB_ID = "broadcast_monthly_performance"
FORECAST_JOB_ID = "compute_forecast"
FORECAST_GRADING_JOB_ID = "grade_forecasts"
FORECAST_INVALIDATION_JOB_ID = "invalidate_forecasts"
OFFICIAL_DAILY_FORECAST_JOB_ID = "generate_official_daily_forecast"
FORECAST_WEEKLY_REVIEW_JOB_ID = "broadcast_forecast_weekly_review"
ALERT_PERFORMANCE_GRADING_JOB_ID = "grade_alert_performance"

# Named session reports and their fire time in UTC. Approximate, DST-naive by
# design (documented in the README): Asia (Tokyo ~9am JST), Europe (London
# ~8am GMT), Morning (US pre-market, ~7am ET), US Open (NYSE bell, ~9:30am
# ET), Daily Summary (US close, ~4pm ET).
SESSION_REPORTS: tuple[tuple[str, int, int], ...] = (
    ("asia", 0, 0),
    ("europe", 7, 0),
    ("morning", 11, 0),
    ("us_open", 13, 30),
    ("daily_summary", 21, 0),
)


def build_market_aggregator() -> MarketDataAggregator:
    repository = MarketRepository(get_session_factory(), get_redis())
    return MarketDataAggregator(repository)


def build_news_aggregator() -> NewsAggregator:
    repository = NewsRepository(get_session_factory())
    return NewsAggregator(repository)


def build_correlation_engine() -> CorrelationEngine:
    return CorrelationEngine(get_session_factory())


def build_regime_detector() -> RegimeDetector:
    market_repository = MarketRepository(get_session_factory(), get_redis())
    return RegimeDetector(get_session_factory(), market_repository)


def build_signal_engine() -> SignalEngine:
    market_repository = MarketRepository(get_session_factory(), get_redis())
    news_repository = NewsRepository(get_session_factory())
    return SignalEngine(get_session_factory(), market_repository, news_repository)


def build_global_score_engine() -> GlobalScoreEngine:
    market_repository = MarketRepository(get_session_factory(), get_redis())
    return GlobalScoreEngine(
        get_session_factory(), market_repository, build_regime_detector(), build_signal_engine()
    )


def build_sentiment_engine() -> SentimentEngine:
    return SentimentEngine(get_session_factory(), NewsRepository(get_session_factory()))


def build_scenario_engine() -> ScenarioEngine:
    return ScenarioEngine(get_session_factory(), build_global_score_engine())


def build_whale_engine() -> WhaleIntelligenceEngine:
    return WhaleIntelligenceEngine(get_session_factory())


def build_etf_engine() -> ETFIntelligenceEngine:
    return ETFIntelligenceEngine(NewsRepository(get_session_factory()), get_session_factory())


def build_economic_calendar_engine() -> EconomicCalendarEngine:
    return EconomicCalendarEngine(get_session_factory())


def build_feature_engine() -> FeatureEngine:
    market_repository = MarketRepository(get_session_factory(), get_redis())
    return FeatureEngine(get_session_factory(), market_repository)


def build_breakout_engine() -> BreakoutEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    regime_detector = RegimeDetector(session_factory, market_repository)
    feature_engine = FeatureEngine(session_factory, market_repository)
    return BreakoutEngine(session_factory, regime_detector, feature_engine)


def build_replay_engine() -> MarketReplayEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    portfolio_engine = PortfolioEngine(session_factory, market_repository)
    portfolio_advisor = PortfolioAdvisorEngine(
        session_factory,
        signal_engine,
        ProbabilityEngine(session_factory),
        portfolio_engine,
        RankingEngine(session_factory),
    )
    return MarketReplayEngine(
        session_factory,
        market_repository,
        news_repository,
        regime_detector,
        global_score_engine,
        build_agent_orchestrator(),
        AgentReliabilityEngine(session_factory),
        portfolio_advisor,
        WhaleIntelligenceEngine(session_factory),
        ETFIntelligenceEngine(news_repository, session_factory),
        ProbabilityEngine(session_factory),
    )


def build_terminal_engine() -> TerminalEngine:
    session_factory = get_session_factory()
    market_repository = MarketRepository(session_factory, get_redis())
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    portfolio_engine = PortfolioEngine(session_factory, market_repository)
    probability_engine = ProbabilityEngine(session_factory)
    portfolio_advisor = PortfolioAdvisorEngine(
        session_factory,
        signal_engine,
        probability_engine,
        portfolio_engine,
        RankingEngine(session_factory),
    )
    feature_engine = FeatureEngine(session_factory, market_repository)
    breakout_engine = BreakoutEngine(session_factory, regime_detector, feature_engine)
    committee_engine = CommitteeEngine(
        build_agent_orchestrator(), AgentReliabilityEngine(session_factory)
    )
    replay_engine = MarketReplayEngine(
        session_factory,
        market_repository,
        news_repository,
        regime_detector,
        global_score_engine,
        build_agent_orchestrator(),
        AgentReliabilityEngine(session_factory),
        portfolio_advisor,
        WhaleIntelligenceEngine(session_factory),
        ETFIntelligenceEngine(news_repository, session_factory),
        probability_engine,
    )
    return TerminalEngine(
        session_factory,
        probability_engine,
        breakout_engine,
        portfolio_advisor,
        portfolio_engine,
        committee_engine,
        global_score_engine,
        replay_engine,
        RankingEngine(session_factory),
        build_watchdog_engine(),
        build_market_scanner_engine(),
    )


# Symbols worth computing features for on every cycle -- crypto majors,
# broad indices and the Magnificent 7, matching _KEY_SYMBOLS in
# app/services/analysis/report.py.
FEATURE_SYMBOLS: tuple[str, ...] = (
    "BTC",
    "ETH",
    "SOL",
    "NASDAQ",
    "SPX",
    "DJI",
    "RUT",
    "AAPL",
    "MSFT",
    "NVDA",
    "TSLA",
    "AMZN",
    "META",
    "GOOGL",
)


async def collect_market_data_job() -> None:
    aggregator = build_market_aggregator()
    try:
        snapshot = await aggregator.collect_and_store()
        logger.info(
            "Market data collected: %d quotes, %d provider errors",
            len(snapshot.quotes),
            len(snapshot.errors),
        )
        # Real, cheap health signal for the v5.4 Watchdog "Provider Status"
        # panel's Reconnect Count -- a consecutive-failure counter per
        # provider, incremented on every failed cycle and reset on the next
        # success. Only CoinGecko/FRED are tracked (the only two providers
        # both wired in AND listed in the mission's Provider Status panel).
        redis = get_redis()
        succeeded = {quote.source for quote in snapshot.quotes}
        failed = {err.split(":", 1)[0] for err in snapshot.errors}
        for provider_name in succeeded:
            await record_provider_success(redis, provider_name)
        for provider_name in failed:
            await record_provider_failure(redis, provider_name)
    except Exception:
        logger.exception("Market data collection job failed")


async def sync_crypto_daily_history_job() -> None:
    """Root-cause fix for a real production bug: ForecastEngine.compute()
    and ProbabilityEngine both source their current_price/ATR/indicator
    basis from CryptoHistory's DAILY rows (see compute()'s own docstring
    on why `latest` is read from get_series(..., Timeframe.DAILY)), but
    until this job existed nothing ever refreshed that table
    automatically -- history sync only ran when someone manually hit
    "Sync now" on Settings or the sync_history.py CLI. A forecast
    computed off a days-old daily close, sitting next to the dashboard's
    live realtime ticker showing the true current price on top of it,
    produces exactly the "AI Forecast target frozen far from the live
    price" divergence users were seeing -- not a model quality problem,
    a stale-data problem.

    Reuses run_sync/HistorySyncEngine.sync_all() verbatim
    (HistorySyncEngine.sync_symbol_timeframe's own docstring: each call
    only asks the provider for candles after the latest stored
    timestamp, so this is cheap and safe on a schedule, never a repeated
    full backfill). Deliberately scoped to just the crypto DAILY rows
    ForecastEngine actually reads -- build_registry()'s ~25-symbol/
    4-provider registry (stocks/macro/forex/FRED) stays manual-trigger-
    only, so this fix adds no load to yfinance (already confirmed
    unreliable from this deployment's egress IP, see registry.py's own
    comment) or other providers this bug has nothing to do with."""
    session_factory = get_session_factory()
    crypto_daily_registry = [
        replace(config, timeframes=(Timeframe.DAILY,))
        for config in build_registry()
        if config.market == "crypto"
    ]
    try:
        await run_sync(session_factory, crypto_daily_registry, years=1)
    except Exception:
        logger.exception("Crypto daily history sync job failed")


async def compute_watchdog_snapshot_job() -> None:
    engine = build_watchdog_engine()
    try:
        snapshot = await engine.run_cycle()
        logger.info(
            "Watchdog snapshot computed: health=%s regime=%s scan_duration_ms=%s",
            snapshot.market_health,
            snapshot.regime,
            snapshot.scan_duration_ms,
        )
    except Exception:
        logger.exception("Watchdog snapshot job failed")


async def compute_market_scan_job() -> None:
    engine = build_market_scanner_engine()
    try:
        result = await engine.run_cycle()
        processed = result["processed"]
        notified = await send_scanner_notifications(get_session_factory(), processed)
        logger.info(
            "Market scan: %d symbols scanned, %d detections, %d Telegram notification(s)",
            result["universe_size"],
            len(processed),
            notified,
        )
    except Exception:
        logger.exception("Market scan job failed")


async def check_critical_alerts_job() -> None:
    engine = build_critical_alert_engine()
    try:
        results = await engine.run_cycle()
        logger.info(
            "Critical alert check: %d detections, %d notified",
            len(results),
            sum(1 for r in results if r["notified"]),
        )
    except Exception:
        logger.exception("Critical alert check job failed")


async def compute_technical_analysis_job() -> None:
    engine = build_technical_analysis_engine()
    computed = 0
    for symbol in TECHNICAL_ANALYSIS_SYMBOLS:
        try:
            result = await engine.analyze(symbol)
            if result is not None:
                computed += 1
        except Exception:
            logger.exception("Technical analysis failed for %s", symbol)
    logger.info(
        "Technical analysis computed for %d/%d symbols", computed, len(TECHNICAL_ANALYSIS_SYMBOLS)
    )


async def collect_news_job() -> None:
    aggregator = build_news_aggregator()
    try:
        inserted = await aggregator.collect_and_store()
        logger.info("News collected: %d new items stored", inserted)
    except Exception:
        logger.exception("News collection job failed")


async def compute_correlations_job() -> None:
    engine = build_correlation_engine()
    try:
        rows = await engine.compute_and_store()
        logger.info("Correlations computed: %d pair/window combinations", len(rows))
    except Exception:
        logger.exception("Correlation computation job failed")


async def detect_regime_job() -> None:
    detector = build_regime_detector()
    try:
        snapshot = await detector.compute_and_store()
        logger.info("Market regime detected: %s", snapshot.regime.value)
    except Exception:
        logger.exception("Regime detection job failed")


async def compute_signals_job() -> None:
    engine = build_signal_engine()
    try:
        snapshot = await engine.compute_and_store()
        logger.info(
            "Signal computed: bull=%d bear=%d net=%d confidence=%d%%",
            snapshot.bull_score,
            snapshot.bear_score,
            snapshot.net_score,
            snapshot.confidence_pct,
        )
    except Exception:
        logger.exception("Signal computation job failed")


async def compute_global_score_job() -> None:
    engine = build_global_score_engine()
    try:
        row = await engine.compute_and_store()
        logger.info(
            "Global Market Score: %s",
            row.global_score if row is not None else "skipped (no regime/signal yet)",
        )
    except Exception:
        logger.exception("Global Market Score job failed")


async def compute_sentiment_job() -> None:
    engine = build_sentiment_engine()
    try:
        snapshot = await engine.compute_and_store()
        logger.info("Sentiment computed: global=%s", snapshot.global_sentiment_score)
    except Exception:
        logger.exception("Sentiment job failed")


async def compute_scenarios_job() -> None:
    engine = build_scenario_engine()
    try:
        row = await engine.compute_and_store()
        logger.info("Scenarios: %s", "skipped (no global score yet)" if row is None else "computed")
    except Exception:
        logger.exception("Scenario job failed")


async def snapshot_whale_etf_job() -> None:
    try:
        await build_whale_engine().compute_and_store("BTC")
    except Exception:
        logger.exception("Whale snapshot job failed")
    try:
        await build_etf_engine().compute_and_store()
    except Exception:
        logger.exception("ETF snapshot job failed")


async def sync_economic_calendar_job() -> None:
    engine = build_economic_calendar_engine()
    try:
        inserted = await engine.sync_fred_releases()
        inserted += await engine.seed_central_bank_meetings()
        logger.info("Economic calendar synced: %d new entries", inserted)
    except Exception:
        logger.exception("Economic calendar sync job failed")


async def compute_features_job() -> None:
    engine = build_feature_engine()
    for symbol in FEATURE_SYMBOLS:
        try:
            await engine.compute_and_store(symbol)
        except Exception:
            logger.exception("Feature computation failed for %s", symbol)


async def compute_breakout_job() -> None:
    engine = build_breakout_engine()
    detections = 0
    for symbol in FEATURE_SYMBOLS:
        config = find_symbol_config(symbol)
        if config is None:
            continue
        try:
            event = await engine.compute_and_store(config.symbol, config.model, Timeframe.DAILY)
            if event is not None:
                detections += 1
        except Exception:
            logger.exception("Breakout detection failed for %s", symbol)
    logger.info(
        "Breakout Intelligence: %d detections across %d symbols", detections, len(FEATURE_SYMBOLS)
    )


async def generate_research_note_job() -> None:
    engine = AIResearcherEngine(get_session_factory())
    try:
        note = await engine.generate_daily_note()
        logger.info("Research note generated: %d discoveries", note.discovery_count)
    except Exception:
        logger.exception("AI Researcher note generation failed")


async def compute_ranking_job() -> None:
    engine = RankingEngine(get_session_factory())
    try:
        row = await engine.compute_and_store("BTC")
        logger.info("Ranking computed: %d factors ranked", len(row.rankings))
    except Exception:
        logger.exception("Ranking computation job failed")


async def compute_forecast_job() -> None:
    """AI Forecast Center -- BTC only for now (this project's flagship
    symbol, matching ConvictionEngine's/PortfolioAdvisorEngine's own
    defaults). Persists one PriceForecastSnapshot per horizon so
    `next_refresh_at` (this job's own APScheduler next_run_time) and the
    dashboard's countdown are meaningful, and so the grading job below has
    real rows to grade."""
    engine = build_forecast_engine()
    for horizon in HORIZONS:
        try:
            payload = await engine.compute("BTC", horizon)
            if payload is None:
                logger.info("Forecast %s/%s: insufficient data this cycle", "BTC", horizon)
        except Exception:
            logger.exception("Forecast computation failed for BTC/%s", horizon)


def official_forecast_symbols() -> tuple[str, ...]:
    """Forecasting 2.0: the roster grade/invalidate/generate-daily all
    share, read fresh from settings each call (not a module-level
    constant) so a config change takes effect without a restart -- same
    pattern realtime_watchlist already uses."""
    return tuple(parse_watchlist(get_settings().official_forecast_symbols))


async def grade_forecasts_job() -> None:
    """AI Forecast Center self-learning: fills in realized_price/error_pct
    on every PriceForecastSnapshot whose horizon has actually elapsed in
    stored history, so future ForecastEngine.compute() calls have a real
    track record to fold into `track_record`. Loops over
    official_forecast_symbols() (BTC/SOL/LINK/UNI by default) -- was BTC
    only until Forecasting 2.0 added official daily forecasts for the
    other three; a symbol with no rows yet (e.g. LINK/UNI before their
    history has synced) simply grades zero, never an error."""
    for symbol in official_forecast_symbols():
        config = find_symbol_config(symbol)
        if config is None:
            continue
        try:
            graded = await grade_price_forecasts(get_session_factory(), symbol, config.model)
            if graded:
                logger.info("Forecast grading: %d %s forecast(s) graded", graded, symbol)
        except Exception:
            logger.exception("Forecast grading job failed for %s", symbol)


async def invalidate_forecasts_job() -> None:
    """AI Forecast Center invalidation: fires structured, machine-checkable
    invalidation rules (see app.services.forecast.invalidation) against
    every still-ACTIVE forecast on each cycle -- independent of, and can
    trigger well before, grade_forecasts_job's horizon-elapsed grading.
    Loops over official_forecast_symbols(), matching grade_forecasts_job."""
    for symbol in official_forecast_symbols():
        config = find_symbol_config(symbol)
        if config is None:
            continue
        try:
            invalidated = await check_and_invalidate_forecasts(
                get_session_factory(), symbol, config.model
            )
            if invalidated:
                logger.info(
                    "Forecast invalidation: %d %s forecast(s) invalidated", invalidated, symbol
                )
        except Exception:
            logger.exception("Forecast invalidation job failed for %s", symbol)


async def generate_official_daily_forecast_job() -> None:
    """Forecasting 2.0 (Part 1-4): the ONE official 24h forecast per
    symbol per UTC calendar day, for official_forecast_symbols() (BTC/
    SOL/LINK/UNI by default) -- distinct from compute_forecast_job's
    BTC-only intraday recomputes above, which keep running independently
    on their own cadence. Reuses the exact same ForecastEngine.compute();
    is_official_daily=True is the only difference, which _persist() uses
    to enforce the one-per-day guarantee (idempotent against a retried
    tick -- see _persist's own docstring). A symbol with insufficient
    synced history (LINK/UNI until their history backfills) honestly
    computes nothing this cycle rather than fabricating a forecast.

    Once every symbol has been attempted, broadcasts a Telegram digest of
    whatever forecasts this cycle actually produced (see
    format_official_daily_digest) -- the exact same payloads compute()
    already returned, no re-fetch. broadcast_text() itself no-ops when
    Telegram isn't configured, so this is a no-op deployment with no
    broadcast chat ids configured."""
    from app.telegram.broadcast import broadcast_text
    from app.telegram.formatters import format_official_daily_digest

    engine = build_forecast_engine()
    payloads = []
    for symbol in official_forecast_symbols():
        try:
            payload = await engine.compute(symbol, "24h", is_official_daily=True)
            if payload is None:
                logger.info("Official daily forecast %s/24h: insufficient data this cycle", symbol)
            else:
                payloads.append(payload)
        except Exception:
            logger.exception("Official daily forecast computation failed for %s/24h", symbol)

    try:
        digest = format_official_daily_digest(payloads, datetime.now(UTC).date().isoformat())
        await broadcast_text(digest)
    except Exception:
        logger.exception("Official daily forecast digest broadcast failed")


async def broadcast_forecast_weekly_review_job() -> None:
    """Forecasting 2.0's "controlled learning-review loop": once a week,
    summarizes how the official-forecast surface actually performed over
    the last 7 days (get_official_performance's own since= window, see
    its docstring for why that's evaluated_at not computed_at) plus
    whatever Learning Center insight the accumulated history now
    supports, and broadcasts it. Deliberately read-only -- there is no
    independent per-agent weight anywhere in this data model to honestly
    tune (see AgentForecast's own docstring), so "controlled" here means
    the review is scoped to real graded outcomes and gated by the same
    sample-size rules as every other Forecasting 2.0 page, not that the
    system mutates its own weights."""
    from app.telegram.broadcast import broadcast_text
    from app.telegram.formatters import format_forecast_weekly_review

    engine = build_forecast_engine()
    symbols = official_forecast_symbols()
    since = datetime.now(UTC) - timedelta(days=7)
    try:
        performance = await engine.get_official_performance(symbols, since=since)
        insights = await engine.get_learning_insights(symbols)
        await broadcast_text(format_forecast_weekly_review(performance, insights, days=7))
    except Exception:
        logger.exception("Forecast weekly review broadcast failed")


async def grade_alert_performance_job() -> None:
    """V9 Increment 9: fills in AlertPerformanceGrade rows for every
    ungraded AlertLog entry whose resolvable symbol has real synced
    history reaching the configured grading horizon past `triggered_at`.
    Unlike the BTC-only forecast jobs above, this grades across every
    symbol an alert's own `data` resolves to -- it's a read-through join
    against whatever history is already synced, not a new per-symbol
    compute."""
    try:
        graded = await grade_alert_performance(get_session_factory())
        if graded:
            logger.info("Alert performance grading: %d alert(s) graded", graded)
    except Exception:
        logger.exception("Alert performance grading job failed")


async def test_hypotheses_job() -> None:
    engine = HypothesisEngine(get_session_factory())
    try:
        results = await engine.test_all()
        logger.info("Hypotheses tested: %d", len(results))
    except Exception:
        logger.exception("Hypothesis testing job failed")


async def check_alerts_job() -> None:
    engine = build_alert_engine()
    try:
        alerts = await engine.check_and_broadcast()
        logger.info(
            "Alert check: %d detections, %d broadcast",
            len(alerts),
            sum(1 for a in alerts if a.broadcast),
        )
    except Exception:
        logger.exception("Alert check job failed")


async def check_alert_rules_job() -> None:
    engine = build_alert_rule_engine()
    try:
        fired = await engine.evaluate_all()
        logger.info("Custom alert rules checked: %d fired", len(fired))
    except Exception:
        logger.exception("Custom alert rules job failed")


async def compute_market_replay_job() -> None:
    engine = build_replay_engine()
    try:
        snapshot = await engine.compute_and_store()
        logger.info(
            "Market replay snapshot stored: regime=%s health=%s alerts=%d",
            snapshot.regime,
            snapshot.health_score,
            len(snapshot.alerts),
        )
    except Exception:
        logger.exception("Market replay snapshot job failed")


async def broadcast_weekly_review_job() -> None:
    engine = build_terminal_engine()
    try:
        result = await engine.compute_period_performance(days=7)
        await broadcast_text(format_weekly_review(result))
        logger.info("Weekly review broadcast: accuracy=%s%%", result["accuracy_pct"])
    except Exception:
        logger.exception("Weekly review job failed")


async def broadcast_monthly_performance_job() -> None:
    engine = build_terminal_engine()
    try:
        result = await engine.compute_period_performance(days=30)
        await broadcast_text(format_monthly_performance(result))
        logger.info("Monthly performance broadcast: accuracy=%s%%", result["accuracy_pct"])
    except Exception:
        logger.exception("Monthly performance job failed")


async def generate_report_job(report_type: str) -> None:
    generator = build_report_generator()
    try:
        report = await generator.generate_and_store(report_type=report_type)
        logger.info("Report generated: type=%s regime=%s", report_type, report.regime)
    except Exception:
        logger.exception("Report generation job failed (type=%s)", report_type)
        return

    try:
        session_factory = get_session_factory()
        sector_breadth = await build_market_scanner_engine().get_latest_sector_breadth()
        replay_comparison = await get_replay_comparison(session_factory)
        watchdog_snapshot = await build_watchdog_engine().get_latest_snapshot()
        watchdog = watchdog_report_input(watchdog_snapshot)
        institutional_report = build_institutional_report(
            report, sector_breadth, replay_comparison, watchdog
        )
        await broadcast_report(report, institutional_report)
    except Exception:
        logger.exception("Report broadcast failed (type=%s)", report_type)


_job_run_status: dict[str, dict] = {}


def get_job_run_status(job_func_name: str) -> dict | None:
    """Forecasting 3.0 (Phase 29, operational health): a real, observed
    record of a job's own recent executions -- last_run_at (every
    invocation, start time), last_success_at (only set if the job
    function returned without an unhandled exception escaping it),
    last_failure_at/last_failure_error (only set if one did). None if
    this job hasn't run since the process started, rather than a
    fabricated timestamp. `job_func_name` is the wrapped function's own
    `__name__` (e.g. "compute_forecast_job"), not the APScheduler job id
    string passed to `scheduler.add_job(id=...)` -- those two are related
    but not always identical, so callers should pass the actual function
    object's `.__name__`, not guess a transform of the job id.

    Caveat worth knowing before reading `last_failure_at` as "is this job
    healthy": several jobs (compute_forecast_job, grade_forecasts_job,
    invalidate_forecasts_job among them) already catch and log exceptions
    per-symbol/per-horizon internally rather than letting them propagate
    -- see the docstring below. That means a real per-symbol failure
    inside one of those never reaches this wrapper as an exception; it's
    still logged (search application logs for "failed"), just not
    reflected here. This field only catches a failure severe enough to
    escape the job function entirely."""
    return _job_run_status.get(job_func_name)


def _timed(job_func):
    """POST-V9 Phase 19 / Forecasting 3.0 Phase 29: wraps a scheduler job
    so every run logs its own real wall-clock duration and records its
    own last-run/last-success/last-failure timestamps (see
    get_job_run_status) -- most jobs here already catch and log their own
    exceptions internally (see the `except Exception:
    logger.exception(...)` block in each job above), so this rarely
    observes a raised exception itself; when it does, it's recorded here
    and re-raised unchanged (APScheduler's own error handling is
    untouched by this). Applied once, at registration in
    start_scheduler(), rather than copy-pasted into every job body."""
    job_name = job_func.__name__

    @functools.wraps(job_func)
    async def _wrapper(*args, **kwargs) -> None:
        start = time.monotonic()
        status = _job_run_status.setdefault(
            job_name,
            {
                "last_run_at": None,
                "last_success_at": None,
                "last_failure_at": None,
                "last_failure_error": None,
            },
        )
        status["last_run_at"] = datetime.now(UTC)
        try:
            await job_func(*args, **kwargs)
        except Exception as exc:
            status["last_failure_at"] = datetime.now(UTC)
            status["last_failure_error"] = str(exc)
            raise
        status["last_success_at"] = datetime.now(UTC)
        elapsed_ms = round((time.monotonic() - start) * 1000, 1)
        logger.info("Job timing: %s completed in %sms", job_name, elapsed_ms)

    return _wrapper


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        _timed(collect_market_data_job),
        trigger=IntervalTrigger(minutes=settings.market_data_interval_minutes, jitter=60),
        id=MARKET_DATA_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(sync_crypto_daily_history_job),
        trigger=IntervalTrigger(minutes=settings.crypto_history_sync_interval_minutes, jitter=90),
        id=CRYPTO_HISTORY_SYNC_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(check_critical_alerts_job),
        trigger=IntervalTrigger(minutes=settings.market_data_interval_minutes, jitter=60),
        id=CRITICAL_ALERT_CHECK_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(compute_technical_analysis_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=TECHNICAL_ANALYSIS_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(compute_watchdog_snapshot_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=WATCHDOG_SNAPSHOT_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(compute_market_scan_job),
        trigger=IntervalTrigger(minutes=settings.scanner_interval_minutes, jitter=120),
        id=MARKET_SCAN_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(collect_news_job),
        trigger=IntervalTrigger(minutes=settings.news_collection_interval_minutes, jitter=90),
        id=NEWS_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(compute_correlations_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=CORRELATION_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(detect_regime_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=REGIME_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(compute_signals_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=SIGNAL_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(compute_global_score_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=GLOBAL_SCORE_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(compute_sentiment_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=SENTIMENT_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(compute_scenarios_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=SCENARIO_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(snapshot_whale_etf_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=WHALE_ETF_SNAPSHOT_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(sync_economic_calendar_job),
        trigger=CronTrigger(hour=2, minute=0, timezone="UTC"),
        id=ECONOMIC_CALENDAR_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(compute_features_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=FEATURE_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(check_alerts_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=ALERT_CHECK_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(check_alert_rules_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=ALERT_RULE_CHECK_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(generate_report_job),
        trigger=IntervalTrigger(minutes=settings.report_interval_minutes, jitter=300),
        id=REPORT_JOB_ID,
        args=["scheduled"],
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(generate_research_note_job),
        trigger=CronTrigger(hour=3, minute=0, timezone="UTC"),
        id=AI_RESEARCHER_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(test_hypotheses_job),
        trigger=CronTrigger(day_of_week="mon", hour=4, minute=0, timezone="UTC"),
        id=HYPOTHESIS_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(compute_ranking_job),
        trigger=CronTrigger(day_of_week="mon", hour=5, minute=0, timezone="UTC"),
        id=RANKING_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(compute_forecast_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=FORECAST_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(grade_forecasts_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=FORECAST_GRADING_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(invalidate_forecasts_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=FORECAST_INVALIDATION_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(generate_official_daily_forecast_job),
        trigger=CronTrigger(hour=settings.daily_forecast_hour_utc, minute=0, timezone="UTC"),
        id=OFFICIAL_DAILY_FORECAST_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(grade_alert_performance_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=ALERT_PERFORMANCE_GRADING_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(compute_market_replay_job),
        trigger=IntervalTrigger(minutes=settings.replay_interval_minutes, jitter=120),
        id=REPLAY_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(compute_breakout_job),
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes, jitter=300),
        id=BREAKOUT_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(broadcast_weekly_review_job),
        trigger=CronTrigger(day_of_week="mon", hour=6, minute=0, timezone="UTC"),
        id=WEEKLY_REVIEW_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(broadcast_monthly_performance_job),
        trigger=CronTrigger(day=1, hour=6, minute=30, timezone="UTC"),
        id=MONTHLY_PERFORMANCE_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        _timed(broadcast_forecast_weekly_review_job),
        trigger=CronTrigger(day_of_week="mon", hour=6, minute=45, timezone="UTC"),
        id=FORECAST_WEEKLY_REVIEW_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    for name, hour, minute in SESSION_REPORTS:
        scheduler.add_job(
            _timed(generate_report_job),
            trigger=CronTrigger(hour=hour, minute=minute, timezone="UTC"),
            id=f"generate_{name}_report",
            args=[name],
            max_instances=1,
            coalesce=True,
        )
    scheduler.start()
    _scheduler = scheduler
    logger.info(
        "Scheduler started: market data every %d min, news every %d min, analysis every %d min, "
        "reports every %d min plus %d daily session reports",
        settings.market_data_interval_minutes,
        settings.news_collection_interval_minutes,
        settings.analysis_interval_minutes,
        settings.report_interval_minutes,
        len(SESSION_REPORTS),
    )
    return scheduler


def shutdown_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None


def get_job_next_run(job_id: str) -> datetime | None:
    """A real, already-tracked-by-APScheduler timestamp -- "Next Scan" for
    the Watchdog hub's Current Market Status/Performance sections. Returns
    None if the scheduler hasn't started yet or the job id is unknown,
    rather than fabricating a guess."""
    if _scheduler is None:
        return None
    job = _scheduler.get_job(job_id)
    return job.next_run_time if job is not None else None


def get_scheduled_job_count() -> int | None:
    """A real proxy for "Queue" in the Watchdog hub's Performance view: how
    many jobs are currently registered with the scheduler. None (not 0) if
    the scheduler hasn't started yet."""
    if _scheduler is None:
        return None
    return len(_scheduler.get_jobs())
