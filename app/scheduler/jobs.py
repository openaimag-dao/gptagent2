import logging
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.api.reports import build_report_generator
from app.config import get_settings
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.agents.orchestrator import build_agent_orchestrator
from app.services.alerts.engine import build_alert_engine
from app.services.analysis.correlation import CorrelationEngine
from app.services.analysis.regime import RegimeDetector
from app.services.breakout.engine import BreakoutEngine
from app.services.calendar.engine import EconomicCalendarEngine
from app.services.committee.engine import CommitteeEngine
from app.services.etf.engine import ETFIntelligenceEngine
from app.services.features.engine import FeatureEngine
from app.services.global_score.engine import GlobalScoreEngine
from app.services.history.registry import find_symbol_config
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
from app.services.reliability.engine import AgentReliabilityEngine
from app.services.replay.engine import MarketReplayEngine
from app.services.research.researcher import AIResearcherEngine
from app.services.scenarios.engine import ScenarioEngine
from app.services.sentiment.engine import SentimentEngine
from app.services.signals.engine import SignalEngine
from app.services.terminal.engine import TerminalEngine
from app.services.whales.engine import WhaleIntelligenceEngine
from app.telegram.broadcast import broadcast_report, broadcast_text
from app.telegram.formatters import format_monthly_performance, format_weekly_review

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

MARKET_DATA_JOB_ID = "collect_market_data"
NEWS_JOB_ID = "collect_news"
CORRELATION_JOB_ID = "compute_correlations"
REGIME_JOB_ID = "detect_regime"
SIGNAL_JOB_ID = "compute_signals"
GLOBAL_SCORE_JOB_ID = "compute_global_score"
SENTIMENT_JOB_ID = "compute_sentiment"
SCENARIO_JOB_ID = "compute_scenarios"
WHALE_ETF_SNAPSHOT_JOB_ID = "snapshot_whale_etf"
ALERT_CHECK_JOB_ID = "check_alerts"
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
        session_factory, signal_engine, ProbabilityEngine(session_factory), portfolio_engine
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
        session_factory, signal_engine, probability_engine, portfolio_engine
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
    except Exception:
        logger.exception("Market data collection job failed")


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
        await broadcast_report(report)
    except Exception:
        logger.exception("Report broadcast failed (type=%s)", report_type)


def start_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is not None:
        return _scheduler

    settings = get_settings()
    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        collect_market_data_job,
        trigger=IntervalTrigger(minutes=settings.market_data_interval_minutes),
        id=MARKET_DATA_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        collect_news_job,
        trigger=IntervalTrigger(minutes=settings.news_collection_interval_minutes),
        id=NEWS_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        compute_correlations_job,
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes),
        id=CORRELATION_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        detect_regime_job,
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes),
        id=REGIME_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        compute_signals_job,
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes),
        id=SIGNAL_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        compute_global_score_job,
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes),
        id=GLOBAL_SCORE_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        compute_sentiment_job,
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes),
        id=SENTIMENT_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        compute_scenarios_job,
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes),
        id=SCENARIO_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        snapshot_whale_etf_job,
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes),
        id=WHALE_ETF_SNAPSHOT_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        sync_economic_calendar_job,
        trigger=CronTrigger(hour=2, minute=0, timezone="UTC"),
        id=ECONOMIC_CALENDAR_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        compute_features_job,
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes),
        id=FEATURE_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        check_alerts_job,
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes),
        id=ALERT_CHECK_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        generate_report_job,
        trigger=IntervalTrigger(minutes=settings.report_interval_minutes),
        id=REPORT_JOB_ID,
        args=["scheduled"],
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        generate_research_note_job,
        trigger=CronTrigger(hour=3, minute=0, timezone="UTC"),
        id=AI_RESEARCHER_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        test_hypotheses_job,
        trigger=CronTrigger(day_of_week="mon", hour=4, minute=0, timezone="UTC"),
        id=HYPOTHESIS_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        compute_ranking_job,
        trigger=CronTrigger(day_of_week="mon", hour=5, minute=0, timezone="UTC"),
        id=RANKING_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        compute_market_replay_job,
        trigger=IntervalTrigger(minutes=settings.replay_interval_minutes),
        id=REPLAY_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        compute_breakout_job,
        trigger=IntervalTrigger(minutes=settings.analysis_interval_minutes),
        id=BREAKOUT_JOB_ID,
        next_run_time=datetime.now(UTC),
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        broadcast_weekly_review_job,
        trigger=CronTrigger(day_of_week="mon", hour=6, minute=0, timezone="UTC"),
        id=WEEKLY_REVIEW_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        broadcast_monthly_performance_job,
        trigger=CronTrigger(day=1, hour=6, minute=30, timezone="UTC"),
        id=MONTHLY_PERFORMANCE_JOB_ID,
        max_instances=1,
        coalesce=True,
    )
    for name, hour, minute in SESSION_REPORTS:
        scheduler.add_job(
            generate_report_job,
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
