import logging
from datetime import UTC, datetime

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import ErrorEvent, Message
from sqlalchemy import select

from app.api.reports import build_report_generator
from app.database.models import AssetClass, HistoricalEvent
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.agents.orchestrator import build_agent_orchestrator
from app.services.alerts.rules import VALID_METRICS, VALID_OPERATORS, build_alert_rule_engine
from app.services.analysis.correlation import CorrelationEngine
from app.services.analysis.regime import RegimeDetector
from app.services.backtest.conditions import Condition
from app.services.backtest.engine import BacktestEngine
from app.services.backtest.strategy_engine import StrategyLabEngine
from app.services.breakout.engine import BreakoutEngine
from app.services.committee.engine import CommitteeEngine
from app.services.consensus.engine import ConsensusEngine
from app.services.conviction.engine import ConvictionEngine
from app.services.etf.engine import ETFIntelligenceEngine
from app.services.explanation.engine import ExplanationEngine
from app.services.features.engine import FeatureEngine
from app.services.global_score.engine import GlobalScoreEngine
from app.services.history.registry import find_symbol_config
from app.services.history.repository import get_series
from app.services.history.schemas import Timeframe
from app.services.hypothesis.engine import HypothesisEngine
from app.services.hypothesis.templates import HypothesisTemplate
from app.services.knowledge.engine import KnowledgeEngine
from app.services.learning.engine import LearningEngine
from app.services.market.repository import MarketRepository
from app.services.memory.engine import CATEGORY_NAMES, MemoryEngine
from app.services.news.repository import NewsRepository
from app.services.onchain.engine import OnChainIntelligenceEngine
from app.services.patterns.engine import PatternEngine
from app.services.portfolio.advisor import PortfolioAdvisorEngine
from app.services.portfolio.engine import PortfolioEngine
from app.services.probability.engine import ProbabilityEngine
from app.services.quality.engine import PredictionQualityEngine
from app.services.ranking.engine import RankingEngine
from app.services.reliability.engine import AgentReliabilityEngine
from app.services.replay.engine import MarketReplayEngine
from app.services.research.engine import ResearchEngine
from app.services.research.impact import EventImpactEngine
from app.services.scanner.engine import build_market_scanner_engine
from app.services.scenarios.engine import ScenarioEngine
from app.services.sentiment.engine import SentimentEngine
from app.services.shocks.engine import build_critical_alert_engine
from app.services.signals.engine import SignalEngine
from app.services.similar_market.engine import SimilarMarketEngine
from app.services.technical.engine import build_technical_analysis_engine
from app.services.terminal.engine import TerminalEngine
from app.services.watchdog.engine import build_watchdog_engine
from app.services.whales.engine import WhaleIntelligenceEngine
from app.services.whatif.engine import WhatIfSimulator
from app.telegram.formatters import (
    format_active_shocks,
    format_advice,
    format_agent_outputs,
    format_alert_history,
    format_alert_rule_created,
    format_alert_rules,
    format_asset_class,
    format_backtest_result,
    format_breakout,
    format_brief,
    format_committee,
    format_consensus,
    format_conviction,
    format_correlations,
    format_etf_proxy,
    format_events,
    format_explanation,
    format_global_score,
    format_historical_comparison,
    format_history,
    format_hypothesis,
    format_hypothesis_list,
    format_knowledge,
    format_learning,
    format_liquidity,
    format_market_summary,
    format_monte_carlo,
    format_monthly_performance,
    format_news,
    format_onchain,
    format_opportunities,
    format_patterns,
    format_portfolio,
    format_probability,
    format_quality,
    format_ranking,
    format_replay,
    format_report,
    format_research_result,
    format_risk,
    format_scanner_dashboard,
    format_scanner_detections,
    format_scanner_movers,
    format_scanner_sectors,
    format_scenarios,
    format_sentiment,
    format_signal,
    format_similar_periods,
    format_single_asset,
    format_status,
    format_strategy_result,
    format_technical,
    format_walk_forward,
    format_watchdog,
    format_watchdog_ai,
    format_watchdog_changes,
    format_watchdog_dashboard,
    format_watchdog_market,
    format_watchdog_onchain,
    format_watchdog_performance,
    format_watchdog_providers,
    format_weekly_review,
    format_whale_snapshot,
    format_whatif,
)

logger = logging.getLogger(__name__)

router = Router()

WELCOME_TEXT = (
    "*AI Market Intelligence Bot*\n\n"
    "I continuously track Bitcoin, the broader crypto market, US equities and the macro "
    "economy, and explain *why* markets are moving -- not just that they moved.\n\n"
    "Use /help to see available commands."
)

HELP_TEXT = (
    "*Available commands*\n\n"
    "/market -- full market summary (crypto, indices, stocks, macro)\n"
    "/btc -- Bitcoin price and 24h change\n"
    "/crypto -- crypto market summary\n"
    "/stocks -- US indices and Magnificent 7 summary\n"
    "/macro -- macro indicators (DXY, Gold, VIX, yields, Fed rate)\n"
    "/news -- latest classified news\n"
    "/signals -- current bull/bear signal score\n"
    "/correlations -- rolling BTC/ETH/SOL correlations\n"
    "/report -- latest AI market analysis report\n"
    "/history SYMBOL [timeframe] -- historical OHLCV + indicators (e.g. /history BTC 1d)\n"
    "/events -- curated historical market events\n"
    "/probability SYMBOL -- empirical next-day up/down probability\n"
    "/learning SYMBOL [timeframe] -- self-learning accuracy: graded past "
    "predictions vs what actually happened\n"
    "/quality SYMBOL [timeframe] -- Prediction Quality Lab: Brier score, "
    "precision/recall, calibration, time-horizon accuracy\n"
    "/patterns SYMBOL -- detected technical patterns\n"
    "/breakout SYMBOL [timeframe] -- breakout/breakdown/false breakout/failed "
    "breakdown/retest/liquidity sweep detection\n"
    "/knowledge SYMBOL -- similar historical episodes for current conditions\n"
    "/brain -- AI Brain: latest institutional-grade synthesis report (alias of /report)\n"
    "/similar SYMBOL [timeframe] -- 25 most similar historical periods\n"
    "/backtest SYMBOL SYMBOL:field:op:value [...] [horizon] -- backtest a rule "
    "(e.g. /backtest BTC BTC:rsi:lt:30 1)\n"
    "/research SYMBOL EVENT [horizon] -- forward returns after an event "
    "(e.g. /research BTC cpi 1; events: cpi/ppi/nfp/gdp/fomc/ecb/boj/pboc/halving/crash/"
    "macro_policy/regulatory/black_swan)\n"
    "/strategy SYMBOL SYMBOL:field:op:value [...] [horizon] [sl=X] [tp=X] [size=X] "
    "[mode=run|walk_forward|monte_carlo] -- backtest with stop-loss/take-profit/position "
    "sizing, walk-forward or Monte Carlo (e.g. /strategy BTC BTC:rsi:lt:30 5 sl=0.05 tp=0.1)\n"
    "/hypothesis [SYMBOL EVENT_A EVENT_B] -- test or list AI hypotheses "
    "(e.g. /hypothesis BTC fomc cpi; no args shows recent ones)\n"
    "/ranking [SYMBOL] -- ranks the signal factors by real predictive power "
    "(current vs historical edge, e.g. /ranking BTC)\n"
    "/whales -- whale/on-chain intelligence (requires a configured data source)\n"
    "/etf -- ETF flow proxy from ETF-category news sentiment\n"
    "/onchain [SYMBOL] -- on-chain intelligence (netflow/SOPR/MVRV/NUPL/TVL/etc, "
    "requires a configured data source)\n"
    "/score -- Global Market Score\n"
    "/agents -- Macro/Crypto/Equity/News/Sentiment agent read-outs\n"
    "/consensus -- bullish/bearish/neutral vote tally across all 5 agents\n"
    "/committee -- AI Investment Committee: majority decision, dissent, "
    "supporting/opposing evidence, final recommendation\n"
    "/brief -- Daily Terminal Brief: committee, risk, top opportunities, portfolio\n"
    "/opportunities -- Top Opportunities across BTC/ETH/SOL (probability + breakout + advisor)\n"
    "/compare [days] -- historical comparison vs N days ago (default 7)\n"
    "/weekly -- Weekly Review: accuracy, alerts, historical comparison\n"
    "/monthly -- Monthly Performance: accuracy, alerts, historical comparison\n"
    "/setalert SYMBOL METRIC OPERATOR THRESHOLD [COOLDOWN_MINUTES] -- create a custom "
    "alert rule (metrics: price, probability_edge, breakout_probability, risk_off_score, "
    "liquidity_score; operators: above, below), e.g. /setalert BTC price above 70000\n"
    "/myrules -- your active custom alert rules\n"
    "/delalert RULE_ID -- delete one of your custom alert rules\n"
    "/alerthistory -- your recently fired custom alerts\n"
    "/scenarios -- probability-weighted forward scenarios\n"
    "/whatif [KEY] -- what-if impact simulator (Fed cuts, DXY drops, Nasdaq crashes, "
    "etc); no args lists scenario keys\n"
    "/sentiment -- Fear & Greed + news sentiment\n"
    "/liquidity -- liquidity + macro pressure sub-scores\n"
    "/conviction [symbol] -- confidence tier for the latest signal/probability\n"
    "/memory [category] -- recent entries from any stored history category\n"
    "/portfolio [add SYMBOL QTY [entry_price]] -- virtual portfolio health\n"
    "/advice SYMBOL [timeframe] -- BUY/SELL/HOLD recommendation with ATR-based "
    "stop-loss/take-profit/position-size (e.g. /advice BTC 1d)\n"
    "/why [symbol] -- evidence pack behind the current read: triggered indicators, "
    "macro drivers, supporting news, historical examples, risk factors, alternative view\n"
    "/risk -- risk-on/off, fear, macro pressure and signal conviction\n"
    "/status -- last-computed timestamps for Signal/Regime/Global Score\n"
    "/health -- bot liveness check\n"
    "/watchdog -- v5.4 Market Monitoring Hub: complete real-time dashboard "
    "(market status, market/crypto/macro/on-chain overview, AI status, what changed, "
    "provider health, alert history)\n"
    "/watchdog events -- recent alert detections and whether each was sent or "
    "suppressed (conviction gate or cooldown) -- the original /watchdog view\n"
    "/watchdog providers -- provider health (CoinGecko/FRED/Binance/DefiLlama/Helius/"
    "Telegram/Database/Brain)\n"
    "/watchdog market -- current market/crypto/macro/on-chain overview\n"
    "/watchdog ai -- committee/consensus/expected scenario/highest risk/biggest opportunity\n"
    "/watchdog changes -- what changed since the last Watchdog cycle\n"
    "/watchdog performance -- cycle timing, memory, CPU load, scheduled job count\n"
    "/scanner -- v5.5 Autonomous Market Scanner: top movers, sector leaders, pending "
    "alerts (no configuration -- the AI decides what's significant across the top ~500 "
    "cryptocurrencies by market cap)\n"
    "/scanner movers -- top 20 gainers/losers\n"
    "/scanner sectors -- sector rotation leaders (Layer 1/2, AI, DeFi, Gaming, Meme, ...)\n"
    "/scanner detections -- latest scanner detections\n"
    "/scanner pending -- currently active (unresolved) scanner alerts\n"
    "/replay -- latest consolidated market snapshot (regime, scores, consensus, "
    "portfolio advice, alerts since the previous snapshot)\n"
    "/shocks -- v5.1 Autonomous Critical Alert System: currently active price-shock "
    "and market-shock episodes (no configuration -- the AI decides what's significant)\n"
    "/technical [SYMBOL] -- v5.3 AI-interpreted technical analysis (TradingView MCP "
    "Institutional Technical Analysis Provider, multi-timeframe): bullish/bearish score, "
    "trend, momentum, breakout/breakdown probability, active signals -- never raw "
    "indicator values (e.g. /technical BTC)"
)

# Registered with Telegram via Bot.set_my_commands() so the client's "/" menu
# is populated -- kept separate from HELP_TEXT since Telegram caps each
# description at 256 chars and disallows newlines.
BOT_COMMANDS: list[tuple[str, str]] = [
    ("start", "Welcome message"),
    ("help", "List all available commands"),
    ("market", "Full market summary (crypto, indices, stocks, macro)"),
    ("btc", "Bitcoin price and 24h change"),
    ("crypto", "Crypto market summary"),
    ("stocks", "US indices and Magnificent 7 summary"),
    ("macro", "Macro indicators (DXY, Gold, VIX, yields, Fed rate)"),
    ("news", "Latest classified news"),
    ("signals", "Current bull/bear signal score"),
    ("correlations", "Rolling BTC/ETH/SOL correlations"),
    ("report", "Latest AI market analysis report"),
    ("history", "Historical OHLCV + indicators, e.g. /history BTC 1d"),
    ("events", "Curated historical market events"),
    ("probability", "Empirical next-day up/down probability"),
    ("learning", "Self-learning accuracy: graded past predictions"),
    ("quality", "Prediction Quality Lab: Brier score, precision/recall, calibration"),
    ("patterns", "Detected technical patterns"),
    ("breakout", "Breakout/breakdown/retest/liquidity sweep detection"),
    ("knowledge", "Similar historical episodes for current conditions"),
    ("brain", "AI Brain synthesis report (alias of /report)"),
    ("similar", "Most similar historical periods"),
    ("backtest", "Backtest a rule, e.g. /backtest BTC BTC:rsi:lt:30 1"),
    ("research", "Forward returns after an event, e.g. /research BTC cpi 1"),
    ("strategy", "Backtest with stop-loss/take-profit/position sizing"),
    ("hypothesis", "Test or list AI hypotheses"),
    ("ranking", "Ranks signal factors by real predictive power"),
    ("whales", "Whale/derivatives positioning intelligence"),
    ("etf", "ETF flow proxy from ETF-category news sentiment"),
    ("onchain", "On-chain intelligence (netflow/SOPR/MVRV/NUPL/TVL/etc)"),
    ("score", "Global Market Score"),
    ("agents", "Macro/Crypto/Equity/News/Sentiment agent read-outs"),
    ("consensus", "Bullish/bearish/neutral vote tally across all 5 agents"),
    ("committee", "AI Investment Committee: majority/dissent/evidence/recommendation"),
    ("brief", "Daily Terminal Brief: committee, risk, top opportunities, portfolio"),
    ("opportunities", "Top Opportunities across BTC/ETH/SOL"),
    ("compare", "Historical comparison vs N days ago"),
    ("weekly", "Weekly Review: accuracy, alerts, historical comparison"),
    ("monthly", "Monthly Performance: accuracy, alerts, historical comparison"),
    ("setalert", "Create a custom alert rule, e.g. /setalert BTC price above 70000"),
    ("myrules", "Your active custom alert rules"),
    ("delalert", "Delete one of your custom alert rules"),
    ("alerthistory", "Your recently fired custom alerts"),
    ("scenarios", "Probability-weighted forward scenarios"),
    ("scenario", "Probability-weighted forward scenarios (alias of /scenarios)"),
    ("whatif", "What-if impact simulator (Fed cuts, DXY drops, Nasdaq crashes, etc)"),
    ("sentiment", "Fear & Greed + news sentiment"),
    ("liquidity", "Liquidity + macro pressure sub-scores"),
    ("conviction", "Confidence tier for the latest signal/probability"),
    ("memory", "Recent entries from any stored history category"),
    ("portfolio", "Virtual portfolio health"),
    ("advice", "BUY/SELL/HOLD recommendation with stop-loss/take-profit/size"),
    ("why", "Evidence pack behind the current read"),
    ("risk", "Risk-on/off, fear, macro pressure and signal conviction"),
    ("status", "Last-computed timestamps for core engines"),
    ("health", "Bot liveness check"),
    ("watchdog", "Market Monitoring Hub -- complete real-time dashboard"),
    ("scanner", "Autonomous Market Scanner -- top movers, sector leaders, alerts"),
    ("replay", "Latest consolidated market snapshot"),
    ("shocks", "Active Autonomous Critical Alert System episodes"),
    ("technical", "AI-interpreted technical analysis (TradingView MCP provider)"),
]


def _market_repository() -> MarketRepository:
    return MarketRepository(get_session_factory(), get_redis())


def _serialize_technical_snapshot(snapshot) -> dict:
    """Maps a stored TechnicalAnalysisSnapshot onto the same dict shape
    TechnicalAnalysisEngine.analyze() returns, so format_technical() can
    handle both a cached read and a freshly computed one identically."""
    return {
        "source": snapshot.source,
        "bullish_score": float(snapshot.bullish_score)
        if snapshot.bullish_score is not None
        else None,
        "bearish_score": float(snapshot.bearish_score)
        if snapshot.bearish_score is not None
        else None,
        "trend_strength": (
            float(snapshot.trend_strength) if snapshot.trend_strength is not None else None
        ),
        "momentum": float(snapshot.momentum) if snapshot.momentum is not None else None,
        "volatility": float(snapshot.volatility) if snapshot.volatility is not None else None,
        "breakout_probability": (
            float(snapshot.breakout_probability)
            if snapshot.breakout_probability is not None
            else None
        ),
        "breakdown_probability": (
            float(snapshot.breakdown_probability)
            if snapshot.breakdown_probability is not None
            else None
        ),
        "confidence": float(snapshot.confidence) if snapshot.confidence is not None else None,
        "active_signals": snapshot.active_signals,
        "timeframes_covered": snapshot.timeframes_covered,
        "support": float(snapshot.support) if snapshot.support is not None else None,
        "resistance": float(snapshot.resistance) if snapshot.resistance is not None else None,
        "high_confidence_alignment": None,
    }


async def _answer(message: Message, text: str) -> None:
    """Sends with Markdown formatting, falling back to plain text.

    Dynamic content (factor names, news titles, LLM-generated report prose)
    can contain characters like a stray "_" or "*" that Telegram's legacy
    Markdown parser treats as an unterminated entity, which raises
    TelegramBadRequest and would otherwise crash the handler.

    The fallback passes parse_mode=None explicitly rather than omitting it:
    the Bot is constructed with a default parse_mode of Markdown (see
    app/telegram/bot.py), and aiogram resolves an omitted parse_mode to
    that bot-level default -- so simply not passing it here would retry
    with the exact same Markdown parsing that just failed.

    Truncated to Telegram's 4096-char message cap here (not per-handler) so
    no command can forget it -- an unbounded reply is also a TelegramBadRequest
    ("message is too long"), which the parse_mode retry above can't fix
    since it isn't a parsing error, so it would otherwise crash the handler.
    """
    text = text[:4090]
    try:
        await message.answer(text, parse_mode="Markdown")
    except TelegramBadRequest:
        await message.answer(text, parse_mode=None)


@router.errors()
async def handle_errors(event: ErrorEvent) -> None:
    """Guarantees every command gets a reply, even when its handler raises.

    Without this, an unhandled exception in a handler (missing data source,
    engine bug, etc.) is only logged -- the user sees no response at all,
    indistinguishable from the bot being down. Converting silence into a
    visible error message is itself the fix for that class of bug.
    """
    logger.error(
        "Unhandled exception while processing update %s",
        event.update.update_id,
        exc_info=event.exception,
    )
    message = event.update.message
    if message is not None:
        try:
            await message.answer("Something went wrong processing that command. Try again shortly.")
        except TelegramBadRequest:
            logger.warning("Failed to notify user of handler error", exc_info=True)


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await _answer(message, WELCOME_TEXT)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await _answer(message, HELP_TEXT)


@router.message(Command("market"))
async def cmd_market(message: Message) -> None:
    assets = await _market_repository().get_latest()
    await _answer(message, format_market_summary(assets))


@router.message(Command("btc"))
async def cmd_btc(message: Message, command: CommandObject) -> None:
    symbol = (command.args or "BTC").strip().upper()
    assets = await _market_repository().get_latest()
    asset = next((a for a in assets if a.symbol == symbol), None)
    await _answer(message, format_single_asset(symbol, asset))


@router.message(Command("crypto"))
async def cmd_crypto(message: Message) -> None:
    assets = await _market_repository().get_latest()
    await _answer(message, format_asset_class(assets, AssetClass.CRYPTO, "Crypto Market"))


@router.message(Command("stocks"))
async def cmd_stocks(message: Message) -> None:
    assets = await _market_repository().get_latest()
    text = "\n\n".join(
        [
            format_asset_class(assets, AssetClass.INDEX, "US Indices"),
            format_asset_class(assets, AssetClass.STOCK, "Magnificent 7"),
        ]
    )
    await _answer(message, text)


@router.message(Command("macro"))
async def cmd_macro(message: Message) -> None:
    assets = await _market_repository().get_latest()
    await _answer(message, format_asset_class(assets, AssetClass.MACRO, "Macro Indicators"))


@router.message(Command("news"))
async def cmd_news(message: Message) -> None:
    news_repository = NewsRepository(get_session_factory())
    items = await news_repository.get_recent(limit=8)
    await _answer(message, format_news(items))


@router.message(Command("signals"))
async def cmd_signals(message: Message) -> None:
    session_factory = get_session_factory()
    market_repository = _market_repository()
    news_repository = NewsRepository(session_factory)
    engine = SignalEngine(session_factory, market_repository, news_repository)
    snapshot = await engine.get_latest()
    await _answer(message, format_signal(snapshot))


@router.message(Command("correlations"))
async def cmd_correlations(message: Message) -> None:
    engine = CorrelationEngine(get_session_factory())
    rows = await engine.get_latest()
    await _answer(message, format_correlations(rows))


@router.message(Command("report"))
async def cmd_report(message: Message) -> None:
    generator = build_report_generator()
    report = await generator.get_latest()
    if report is None:
        await _answer(message, format_report(None))
        return

    await _answer(message, format_report(report))


def _parse_symbol_and_timeframe(command: CommandObject, default_symbol: str = "BTC") -> tuple:
    parts = (command.args or "").split()
    symbol = (parts[0] if parts else default_symbol).upper()
    timeframe_arg = parts[1] if len(parts) > 1 else "1d"
    try:
        timeframe = Timeframe(timeframe_arg)
    except ValueError:
        timeframe = Timeframe.DAILY
        timeframe_arg = "1d"
    return symbol, timeframe, timeframe_arg


@router.message(Command("history"))
async def cmd_history(message: Message, command: CommandObject) -> None:
    symbol, timeframe, timeframe_arg = _parse_symbol_and_timeframe(command)
    config = find_symbol_config(symbol)
    if config is None or timeframe not in config.timeframes:
        await _answer(message, f"No historical data available for {symbol}/{timeframe_arg}.")
        return

    rows = await get_series(get_session_factory(), config.model, config.symbol, timeframe)
    await _answer(message, format_history(config.symbol, timeframe_arg, rows))


@router.message(Command("events"))
async def cmd_events(message: Message) -> None:
    async with get_session_factory()() as session:
        events = list(
            await session.scalars(select(HistoricalEvent).order_by(HistoricalEvent.event_date))
        )
    await _answer(message, format_events(events))


@router.message(Command("probability"))
async def cmd_probability(message: Message, command: CommandObject) -> None:
    symbol, timeframe, timeframe_arg = _parse_symbol_and_timeframe(command)
    config = find_symbol_config(symbol)
    if config is None or timeframe not in config.timeframes:
        await _answer(message, f"No historical data available for {symbol}/{timeframe_arg}.")
        return

    engine = ProbabilityEngine(get_session_factory())
    snapshot = await engine.compute_and_store(config.symbol, config.model, timeframe)
    await _answer(message, format_probability(snapshot))


@router.message(Command("learning"))
async def cmd_learning(message: Message, command: CommandObject) -> None:
    symbol, timeframe, timeframe_arg = _parse_symbol_and_timeframe(command)
    config = find_symbol_config(symbol)
    if config is None or timeframe not in config.timeframes:
        await _answer(message, f"No historical data available for {symbol}/{timeframe_arg}.")
        return

    engine = LearningEngine(get_session_factory())
    result = await engine.evaluate_accuracy(config.symbol, config.model, timeframe)
    await _answer(message, format_learning(result, config.symbol, timeframe_arg))


@router.message(Command("quality"))
async def cmd_quality(message: Message, command: CommandObject) -> None:
    symbol, timeframe, timeframe_arg = _parse_symbol_and_timeframe(command)
    config = find_symbol_config(symbol)
    if config is None or timeframe not in config.timeframes:
        await _answer(message, f"No historical data available for {symbol}/{timeframe_arg}.")
        return

    engine = PredictionQualityEngine(get_session_factory())
    result = await engine.evaluate(config.symbol, config.model, timeframe)
    await _answer(message, format_quality(result, config.symbol, timeframe_arg))


@router.message(Command("patterns"))
async def cmd_patterns(message: Message, command: CommandObject) -> None:
    symbol, timeframe, timeframe_arg = _parse_symbol_and_timeframe(command)
    config = find_symbol_config(symbol)
    if config is None or timeframe not in config.timeframes:
        await _answer(message, f"No historical data available for {symbol}/{timeframe_arg}.")
        return

    session_factory = get_session_factory()
    engine = PatternEngine(session_factory)
    await engine.compute_and_store(config.symbol, config.model, timeframe)
    patterns = await engine.get_latest(config.symbol, timeframe)
    await _answer(message, format_patterns(config.symbol, patterns))


@router.message(Command("breakout"))
async def cmd_breakout(message: Message, command: CommandObject) -> None:
    symbol, timeframe, timeframe_arg = _parse_symbol_and_timeframe(command)
    config = find_symbol_config(symbol)
    if config is None or timeframe not in config.timeframes:
        await _answer(message, f"No historical data available for {symbol}/{timeframe_arg}.")
        return

    session_factory = get_session_factory()
    market_repository = _market_repository()
    regime_detector = RegimeDetector(session_factory, market_repository)
    feature_engine = FeatureEngine(session_factory, market_repository)
    engine = BreakoutEngine(session_factory, regime_detector, feature_engine)
    await engine.compute_and_store(config.symbol, config.model, timeframe)
    event = await engine.get_latest(config.symbol, timeframe)
    await _answer(message, format_breakout(config.symbol, event))


@router.message(Command("knowledge"))
async def cmd_knowledge(message: Message, command: CommandObject) -> None:
    symbol, timeframe, timeframe_arg = _parse_symbol_and_timeframe(command)
    config = find_symbol_config(symbol)
    if config is None or timeframe not in config.timeframes:
        await _answer(message, f"No historical data available for {symbol}/{timeframe_arg}.")
        return

    engine = KnowledgeEngine(get_session_factory())
    analogs = await engine.find_analogs(config.symbol, config.model, timeframe)
    await _answer(message, format_knowledge(config.symbol, analogs))


@router.message(Command("brain"))
async def cmd_brain(message: Message) -> None:
    """AI Brain -- alias of /report; same institutional synthesis, different name."""
    await cmd_report(message)


@router.message(Command("score"))
async def cmd_score(message: Message) -> None:
    session_factory = get_session_factory()
    market_repository = _market_repository()
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    engine = GlobalScoreEngine(session_factory, market_repository, regime_detector, signal_engine)
    row = await engine.compute_and_store()
    await _answer(message, format_global_score(row))


@router.message(Command("similar"))
async def cmd_similar(message: Message, command: CommandObject) -> None:
    symbol, timeframe, timeframe_arg = _parse_symbol_and_timeframe(command)
    config = find_symbol_config(symbol)
    if config is None or timeframe not in config.timeframes:
        await _answer(message, f"No historical data available for {symbol}/{timeframe_arg}.")
        return

    engine = SimilarMarketEngine(get_session_factory())
    matches = await engine.find_and_store(config.symbol, config.model, timeframe)
    await _answer(message, format_similar_periods(config.symbol, matches))


@router.message(Command("whales"))
async def cmd_whales(message: Message, command: CommandObject) -> None:
    symbol = (command.args or "BTC").strip().upper()
    engine = WhaleIntelligenceEngine()
    snapshot = await engine.get_snapshot(symbol)
    await _answer(message, format_whale_snapshot(snapshot))


@router.message(Command("etf"))
async def cmd_etf(message: Message) -> None:
    engine = ETFIntelligenceEngine(NewsRepository(get_session_factory()))
    data = await engine.get_flow_proxy()
    await _answer(message, format_etf_proxy(data))


@router.message(Command("onchain"))
async def cmd_onchain(message: Message, command: CommandObject) -> None:
    symbol = (command.args or "BTC").strip().upper()
    engine = OnChainIntelligenceEngine()
    snapshot = await engine.get_snapshot(symbol)
    await _answer(message, format_onchain(snapshot))


def _parse_condition(token: str) -> Condition | None:
    parts = token.split(":")
    if len(parts) != 4:
        return None
    symbol, field, operator, raw_value = parts
    try:
        value = float(raw_value)
        return Condition(symbol=symbol.upper(), field=field, operator=operator, value=value)
    except ValueError:
        return None


@router.message(Command("backtest"))
async def cmd_backtest(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    if len(parts) < 2:
        await _answer(
            message,
            "Usage: /backtest SYMBOL SYMBOL:field:op:value [...] [horizon]\n"
            "Example: /backtest BTC BTC:rsi:lt:30 1",
        )
        return

    target_symbol = parts[0].upper()
    horizon = 1
    condition_tokens = parts[1:]
    if condition_tokens and condition_tokens[-1].isdigit():
        horizon = int(condition_tokens[-1])
        condition_tokens = condition_tokens[:-1]

    conditions = [_parse_condition(t) for t in condition_tokens]
    if not condition_tokens or any(c is None for c in conditions):
        await _answer(
            message,
            "Couldn't parse conditions. Use SYMBOL:field:op:value, e.g. BTC:rsi:lt:30 "
            "(field: rsi/return_pct/sma_50/sma_200/...; op: gt/lt/gte/lte).",
        )
        return

    engine = BacktestEngine(get_session_factory())
    result = await engine.run(conditions, target_symbol, horizon=horizon)
    await _answer(message, format_backtest_result(result))


@router.message(Command("research"))
async def cmd_research(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    if len(parts) < 2:
        await _answer(
            message,
            "Usage: /research SYMBOL EVENT [horizon]\n"
            "Example: /research BTC cpi 1\n"
            "Events: cpi, ppi, nfp, gdp, fomc, ecb, boj, pboc, halving, crash, "
            "macro_policy, regulatory, black_swan",
        )
        return

    symbol, event = parts[0].upper(), parts[1].lower()
    horizon = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1

    engine = ResearchEngine(get_session_factory())
    result = await engine.test_hypothesis(symbol, event, horizon=horizon)
    await _answer(message, format_research_result(result))


@router.message(Command("strategy"))
async def cmd_strategy(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    if len(parts) < 2:
        await _answer(
            message,
            "Usage: /strategy SYMBOL SYMBOL:field:op:value [...] [horizon] "
            "[sl=X] [tp=X] [size=X] [mode=run|walk_forward|monte_carlo]\n"
            "Example: /strategy BTC BTC:rsi:lt:30 5 sl=0.05 tp=0.1 mode=monte_carlo",
        )
        return

    target_symbol = parts[0].upper()
    kv_tokens = [p for p in parts[1:] if "=" in p]
    remaining = [p for p in parts[1:] if "=" not in p]

    horizon = 1
    if remaining and remaining[-1].isdigit():
        horizon = int(remaining[-1])
        remaining = remaining[:-1]

    conditions = [_parse_condition(t) for t in remaining]
    if not remaining or any(c is None for c in conditions):
        await _answer(
            message,
            "Couldn't parse conditions. Use SYMBOL:field:op:value, e.g. BTC:rsi:lt:30.",
        )
        return

    kv = dict(token.split("=", 1) for token in kv_tokens)
    try:
        stop_loss_pct = float(kv["sl"]) if "sl" in kv else None
        take_profit_pct = float(kv["tp"]) if "tp" in kv else None
        position_size_pct = float(kv["size"]) if "size" in kv else 1.0
    except ValueError:
        await _answer(message, "sl/tp/size must be numbers, e.g. sl=0.05")
        return

    mode = kv.get("mode", "run")
    engine = StrategyLabEngine(get_session_factory())
    common_kwargs = dict(
        conditions=conditions,
        target_symbol=target_symbol,
        horizon=horizon,
        stop_loss_pct=stop_loss_pct,
        take_profit_pct=take_profit_pct,
        position_size_pct=position_size_pct,
    )

    if mode == "walk_forward":
        results = await engine.walk_forward(**common_kwargs)
        await _answer(message, format_walk_forward(results))
    elif mode == "monte_carlo":
        result = await engine.monte_carlo(**common_kwargs)
        await _answer(message, format_monte_carlo(result))
    else:
        result = await engine.run(**common_kwargs)
        await _answer(message, format_strategy_result(result))


@router.message(Command("hypothesis"))
async def cmd_hypothesis(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    engine = HypothesisEngine(get_session_factory())

    if not parts:
        rows = await engine.get_latest(limit=10)
        await _answer(message, format_hypothesis_list(rows))
        return

    if len(parts) < 3:
        await _answer(
            message,
            "Usage: /hypothesis SYMBOL EVENT_A EVENT_B -- tests a new hypothesis\n"
            "Usage: /hypothesis -- shows the 10 most recently tested hypotheses\n"
            "Example: /hypothesis BTC fomc cpi",
        )
        return

    hypothesis = HypothesisTemplate(
        symbol=parts[0].upper(), event_a=parts[1].lower(), event_b=parts[2].lower()
    )
    row = await engine.test(hypothesis)
    await _answer(message, format_hypothesis(row))


@router.message(Command("ranking"))
async def cmd_ranking(message: Message, command: CommandObject) -> None:
    symbol = (command.args or "BTC").strip().upper() or "BTC"
    engine = RankingEngine(get_session_factory())
    row = await engine.get_latest(symbol)
    if row is None:
        row = await engine.compute_and_store(symbol)
    await _answer(message, format_ranking(row))


@router.message(Command("agents"))
async def cmd_agents(message: Message) -> None:
    orchestrator = build_agent_orchestrator()
    outputs = await orchestrator.run_all()
    await _answer(message, format_agent_outputs(outputs))


@router.message(Command("consensus"))
async def cmd_consensus(message: Message) -> None:
    engine = ConsensusEngine(
        build_agent_orchestrator(), AgentReliabilityEngine(get_session_factory())
    )
    result = await engine.compute()
    await _answer(message, format_consensus(result))


@router.message(Command("committee"))
async def cmd_committee(message: Message) -> None:
    engine = CommitteeEngine(
        build_agent_orchestrator(), AgentReliabilityEngine(get_session_factory())
    )
    verdict = await engine.convene()
    await _answer(message, format_committee(verdict.to_dict() if verdict is not None else None))


def _build_terminal_engine() -> TerminalEngine:
    session_factory = get_session_factory()
    market_repository = _market_repository()
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


@router.message(Command("brief"))
async def cmd_brief(message: Message) -> None:
    engine = _build_terminal_engine()
    brief = await engine.compute_brief()
    await _answer(message, format_brief(brief))


@router.message(Command("opportunities"))
async def cmd_opportunities(message: Message) -> None:
    engine = _build_terminal_engine()
    opportunities = await engine.compute_top_opportunities()
    await _answer(message, format_opportunities(opportunities))


@router.message(Command("compare"))
async def cmd_compare_history(message: Message, command: CommandObject) -> None:
    days_arg = (command.args or "7").strip()
    try:
        days = int(days_arg)
    except ValueError:
        days = 7
    engine = _build_terminal_engine()
    result = await engine.compute_historical_comparison(days_ago=days)
    await _answer(message, format_historical_comparison(result))


@router.message(Command("weekly"))
async def cmd_weekly(message: Message) -> None:
    engine = _build_terminal_engine()
    result = await engine.compute_period_performance(days=7)
    await _answer(message, format_weekly_review(result))


@router.message(Command("monthly"))
async def cmd_monthly(message: Message) -> None:
    engine = _build_terminal_engine()
    result = await engine.compute_period_performance(days=30)
    await _answer(message, format_monthly_performance(result))


@router.message(Command("setalert"))
async def cmd_set_alert(message: Message, command: CommandObject) -> None:
    parts = (command.args or "").split()
    if len(parts) < 4:
        await _answer(
            message,
            "Usage: /setalert SYMBOL METRIC OPERATOR THRESHOLD [COOLDOWN_MINUTES]\n"
            f"Metrics: {', '.join(VALID_METRICS)}\n"
            f"Operators: {', '.join(VALID_OPERATORS)}",
        )
        return
    symbol, metric, operator, threshold_arg, *rest = parts
    try:
        threshold = float(threshold_arg)
        cooldown_minutes = int(rest[0]) if rest else 60
    except ValueError:
        await _answer(message, "Threshold and cooldown minutes must be numbers.")
        return

    engine = build_alert_rule_engine()
    try:
        rule = await engine.create_rule(
            str(message.chat.id), symbol, metric, operator, threshold, cooldown_minutes
        )
    except ValueError as exc:
        await _answer(message, str(exc))
        return
    await _answer(message, format_alert_rule_created(rule))


@router.message(Command("myrules"))
async def cmd_my_rules(message: Message) -> None:
    engine = build_alert_rule_engine()
    rules = await engine.list_rules(str(message.chat.id))
    await _answer(message, format_alert_rules(rules))


@router.message(Command("delalert"))
async def cmd_delete_alert(message: Message, command: CommandObject) -> None:
    arg = (command.args or "").strip()
    try:
        rule_id = int(arg)
    except ValueError:
        await _answer(message, "Usage: /delalert RULE_ID (see /myrules for ids)")
        return
    engine = build_alert_rule_engine()
    removed = await engine.delete_rule(rule_id, str(message.chat.id))
    await _answer(message, "Rule deleted." if removed else "No rule with that id owned by you.")


@router.message(Command("alerthistory"))
async def cmd_alert_history(message: Message) -> None:
    engine = build_alert_rule_engine()
    history = await engine.recent_history(str(message.chat.id), limit=10)
    await _answer(message, format_alert_history(history))


@router.message(Command("scenarios"))
async def cmd_scenarios(message: Message) -> None:
    session_factory = get_session_factory()
    market_repository = _market_repository()
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    engine = ScenarioEngine(session_factory, global_score_engine)
    row = await engine.compute_and_store()
    await _answer(message, format_scenarios(row))


@router.message(Command("scenario"))
async def cmd_scenario(message: Message) -> None:
    """Singular alias of /scenarios."""
    await cmd_scenarios(message)


@router.message(Command("whatif"))
async def cmd_whatif(message: Message, command: CommandObject) -> None:
    session_factory = get_session_factory()
    market_repository = _market_repository()
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(
        session_factory, market_repository, NewsRepository(session_factory)
    )
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    simulator = WhatIfSimulator(
        EventImpactEngine(session_factory),
        CorrelationEngine(session_factory),
        regime_detector,
        global_score_engine,
        ProbabilityEngine(session_factory),
    )
    scenario_key = (command.args or "").strip()
    if not scenario_key:
        scenarios = simulator.list_scenarios()
        lines = ["*WHAT-IF SCENARIOS*", "", "Use /whatif KEY. Available:"]
        lines.extend(f"- {s['key']}: {s['label']}" for s in scenarios)
        await _answer(message, "\n".join(lines))
        return
    result = await simulator.simulate(scenario_key)
    await _answer(message, format_whatif(result))


@router.message(Command("sentiment"))
async def cmd_sentiment(message: Message) -> None:
    session_factory = get_session_factory()
    engine = SentimentEngine(session_factory, NewsRepository(session_factory))
    row = await engine.compute_and_store()
    await _answer(message, format_sentiment(row))


@router.message(Command("liquidity"))
async def cmd_liquidity(message: Message) -> None:
    session_factory = get_session_factory()
    market_repository = _market_repository()
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    engine = GlobalScoreEngine(session_factory, market_repository, regime_detector, signal_engine)
    row = await engine.compute_and_store()
    if row is None:
        await _answer(message, "Not enough data yet -- run /score first.")
        return
    await _answer(
        message,
        format_liquidity(
            {
                "liquidity_score": row.liquidity_score,
                "macro_pressure_score": row.macro_pressure_score,
                "risk_on_score": row.risk_on_score,
                "risk_off_score": row.risk_off_score,
            }
        ),
    )


@router.message(Command("conviction"))
async def cmd_conviction(message: Message, command: CommandObject) -> None:
    symbol = (command.args or "BTC").strip().upper()
    session_factory = get_session_factory()
    market_repository = _market_repository()
    news_repository = NewsRepository(session_factory)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    probability_engine = ProbabilityEngine(session_factory)
    engine = ConvictionEngine(signal_engine, probability_engine)
    signal_conviction = await engine.evaluate_signal()
    probability_conviction = await engine.evaluate_probability(symbol, Timeframe.DAILY)
    await _answer(
        message,
        format_conviction(
            {
                "signal": signal_conviction,
                "probability": (
                    {"symbol": symbol, **probability_conviction}
                    if probability_conviction is not None
                    else None
                ),
            }
        ),
    )


@router.message(Command("memory"))
async def cmd_memory(message: Message, command: CommandObject) -> None:
    category = (command.args or "").strip() or None
    engine = MemoryEngine(get_session_factory())
    if category is not None and category not in CATEGORY_NAMES:
        await _answer(
            message,
            f"Unknown category '{category}'. Valid: {', '.join(CATEGORY_NAMES)}",
        )
        return

    entries = (
        await engine.get_category(category, limit=10)
        if category is not None
        else await engine.get_timeline(limit=10)
    )
    if not entries:
        await _answer(message, "No memory entries yet for this category.")
        return

    lines = ["*MARKET MEMORY*", ""]
    for entry in entries:
        lines.append(f"[{entry['category']}] {entry['timestamp']}: {entry['summary']}")
    await _answer(message, "\n".join(lines))


@router.message(Command("portfolio"))
async def cmd_portfolio(message: Message, command: CommandObject) -> None:
    session_factory = get_session_factory()
    engine = PortfolioEngine(session_factory, _market_repository())
    portfolio = await engine.get_or_create("main")

    parts = (command.args or "").split()
    if parts and parts[0].lower() == "add" and len(parts) >= 3:
        symbol, quantity_raw = parts[1], parts[2]
        try:
            quantity = float(quantity_raw)
            entry_price = float(parts[3]) if len(parts) > 3 else None
            await engine.add_position(portfolio.id, symbol, quantity, entry_price)
        except ValueError as exc:
            await _answer(message, f"Couldn't add position: {exc}")
            return

    health = await engine.compute_health(portfolio.id)
    await _answer(message, format_portfolio(health))


@router.message(Command("advice"))
async def cmd_advice(message: Message, command: CommandObject) -> None:
    symbol, timeframe, timeframe_arg = _parse_symbol_and_timeframe(command)

    session_factory = get_session_factory()
    market_repository = _market_repository()
    news_repository = NewsRepository(session_factory)
    portfolio_engine = PortfolioEngine(session_factory, market_repository)
    portfolio = await portfolio_engine.get_or_create("main")

    advisor = PortfolioAdvisorEngine(
        session_factory,
        SignalEngine(session_factory, market_repository, news_repository),
        ProbabilityEngine(session_factory),
        portfolio_engine,
    )
    advice = await advisor.advise(symbol, timeframe, portfolio_id=portfolio.id)
    await _answer(
        message,
        format_advice(advice.to_dict() if advice is not None else None, symbol, timeframe_arg),
    )


@router.message(Command("health"))
async def cmd_health(message: Message) -> None:
    await _answer(message, f"Bot is running. {datetime.now(UTC).isoformat()}")


async def _watchdog_next_scan() -> str | None:
    # Lazy import: app.scheduler.jobs imports app.telegram.broadcast at
    # module level, which imports app.telegram.bot, which imports this
    # module (app.telegram.handlers) back -- a module-level import here
    # would be circular (same fix as build_critical_alert_engine's/
    # AlertRuleEngine's Telegram sends elsewhere in this codebase).
    from app.scheduler.jobs import WATCHDOG_SNAPSHOT_JOB_ID, get_job_next_run

    next_run = get_job_next_run(WATCHDOG_SNAPSHOT_JOB_ID)
    return next_run.isoformat() if next_run is not None else None


@router.message(Command("watchdog"))
async def cmd_watchdog(message: Message, command: CommandObject) -> None:
    sub = (command.args or "").strip().lower()
    engine = build_watchdog_engine()

    if sub == "events":
        entries = await engine.get_alert_history(limit=10)
        await _answer(message, format_watchdog(entries))
        return
    if sub == "providers":
        providers = await engine.get_provider_status()
        await _answer(message, format_watchdog_providers(providers))
        return
    if sub == "market":
        market, crypto, macro, onchain = (
            await engine.get_market_overview(),
            await engine.get_crypto_overview(),
            await engine.get_macro_overview(),
            await engine.get_onchain_overview(),
        )
        market_text = format_watchdog_market(market, crypto, macro)
        text = f"{market_text}\n\n{format_watchdog_onchain(onchain)}"
        await _answer(message, text)
        return
    if sub == "ai":
        ai_status = await engine.get_ai_status()
        await _answer(message, format_watchdog_ai(ai_status))
        return
    if sub == "changes":
        changes = await engine.get_what_changed()
        await _answer(message, format_watchdog_changes(changes))
        return
    if sub == "performance":
        status = await engine.get_current_status()
        status["next_scan"] = await _watchdog_next_scan()
        await _answer(message, format_watchdog_performance(status))
        return

    dashboard = await engine.get_dashboard()
    dashboard["current_status"]["next_scan"] = await _watchdog_next_scan()
    await _answer(message, format_watchdog_dashboard(dashboard))


def _serialize_scanner_alert(row) -> dict:
    return {
        "alert_key": row.alert_key,
        "category": row.category,
        "tier": row.tier,
        "symbols": row.symbols,
        "message": row.message,
        "active": row.active,
        "last_updated_at": row.last_updated_at.isoformat(),
    }


@router.message(Command("scanner"))
async def cmd_scanner(message: Message, command: CommandObject) -> None:
    sub = (command.args or "").strip().lower()
    engine = build_market_scanner_engine()

    if sub == "movers":
        breadth = await engine.get_latest_breadth()
        await _answer(message, format_scanner_movers(breadth))
        return
    if sub == "sectors":
        sectors = await engine.get_latest_sector_breadth()
        await _answer(message, format_scanner_sectors(sectors))
        return
    if sub == "detections":
        alerts = await engine.list_recent_alerts(limit=20)
        serialized = [_serialize_scanner_alert(a) for a in alerts]
        await _answer(message, format_scanner_detections(serialized))
        return
    if sub == "pending":
        alerts = await engine.list_active_alerts()
        serialized = [_serialize_scanner_alert(a) for a in alerts]
        await _answer(message, format_scanner_detections(serialized))
        return

    breadth = await engine.get_latest_breadth()
    sector_breadth = await engine.get_latest_sector_breadth()
    pending = await engine.list_active_alerts()
    suppressed = await engine.list_suppressed_alerts(limit=50)
    market_context = await engine.get_market_context()
    dashboard = {
        "top_movers": breadth,
        "sector_leaders": sector_breadth,
        "pending_alerts": pending,
        "suppressed_alerts": suppressed,
        "market_context": market_context,
    }
    await _answer(message, format_scanner_dashboard(dashboard))


@router.message(Command("shocks"))
async def cmd_shocks(message: Message) -> None:
    engine = build_critical_alert_engine()
    rows = await engine.list_active()
    await _answer(message, format_active_shocks(rows))


@router.message(Command("technical"))
async def cmd_technical(message: Message, command: CommandObject) -> None:
    symbol = (command.args or "BTC").strip().upper()
    engine = build_technical_analysis_engine()
    snapshot = await engine.get_latest(symbol)
    result = _serialize_technical_snapshot(snapshot) if snapshot is not None else None
    if result is None:
        result = await engine.analyze(symbol)
    await _answer(message, format_technical(symbol, result))


@router.message(Command("status"))
async def cmd_status(message: Message) -> None:
    session_factory = get_session_factory()
    market_repository = _market_repository()
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )

    signal_snapshot = await signal_engine.get_latest()
    regime_snapshot = await regime_detector.get_latest()
    global_score = await global_score_engine.get_latest()

    await _answer(
        message,
        format_status(
            {
                "Signal": signal_snapshot.computed_at if signal_snapshot is not None else None,
                "Regime": regime_snapshot.computed_at if regime_snapshot is not None else None,
                "Global Score": global_score.computed_at if global_score is not None else None,
            }
        ),
    )


@router.message(Command("risk"))
async def cmd_risk(message: Message) -> None:
    session_factory = get_session_factory()
    market_repository = _market_repository()
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    conviction_engine = ConvictionEngine(signal_engine, ProbabilityEngine(session_factory))

    global_score = await global_score_engine.get_latest()
    signal_conviction = await conviction_engine.evaluate_signal()

    await _answer(
        message,
        format_risk(
            {
                "global_score": (
                    {
                        "risk_off_score": global_score.risk_off_score,
                        "risk_on_score": global_score.risk_on_score,
                        "fear_score": global_score.fear_score,
                        "macro_pressure_score": global_score.macro_pressure_score,
                    }
                    if global_score is not None
                    else None
                ),
                "signal_conviction": signal_conviction,
            }
        ),
    )


@router.message(Command("why"))
async def cmd_why(message: Message, command: CommandObject) -> None:
    symbol = (command.args or "BTC").strip().upper()
    session_factory = get_session_factory()
    market_repository = _market_repository()
    news_repository = NewsRepository(session_factory)
    regime_detector = RegimeDetector(session_factory, market_repository)
    signal_engine = SignalEngine(session_factory, market_repository, news_repository)
    global_score_engine = GlobalScoreEngine(
        session_factory, market_repository, regime_detector, signal_engine
    )
    scenario_engine = ScenarioEngine(session_factory, global_score_engine)
    engine = ExplanationEngine(
        session_factory,
        signal_engine,
        regime_detector,
        news_repository,
        global_score_engine,
        scenario_engine,
    )
    data = await engine.build(symbol)
    await _answer(message, format_explanation(data))


@router.message(Command("replay"))
async def cmd_replay(message: Message) -> None:
    session_factory = get_session_factory()
    market_repository = _market_repository()
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
    engine = MarketReplayEngine(
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
    row = await engine.get_latest()
    snapshot = (
        {
            "regime": row.regime,
            "health_score": row.health_score,
            "trend_strength_score": row.trend_strength_score,
            "risk_score": row.risk_score,
            "confidence_score": row.confidence_score,
            "consensus": row.consensus,
            "portfolio_advice": row.portfolio_advice,
            "alerts": row.alerts,
            "computed_at": row.computed_at.isoformat(),
        }
        if row is not None
        else None
    )
    await _answer(message, format_replay(snapshot))
