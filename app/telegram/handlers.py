import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.api.reports import build_report_generator
from app.database.models import AssetClass
from app.database.redis import get_redis
from app.database.session import get_session_factory
from app.services.analysis.correlation import CorrelationEngine
from app.services.market.repository import MarketRepository
from app.services.news.repository import NewsRepository
from app.services.signals.engine import SignalEngine
from app.telegram.formatters import (
    format_asset_class,
    format_correlations,
    format_market_summary,
    format_news,
    format_report,
    format_signal,
    format_single_asset,
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
    "/report -- latest AI market analysis report"
)


def _market_repository() -> MarketRepository:
    return MarketRepository(get_session_factory(), get_redis())


@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    await message.answer(WELCOME_TEXT, parse_mode="Markdown")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP_TEXT, parse_mode="Markdown")


@router.message(Command("market"))
async def cmd_market(message: Message) -> None:
    assets = await _market_repository().get_latest()
    await message.answer(format_market_summary(assets), parse_mode="Markdown")


@router.message(Command("btc"))
async def cmd_btc(message: Message, command: CommandObject) -> None:
    symbol = (command.args or "BTC").strip().upper()
    assets = await _market_repository().get_latest()
    asset = next((a for a in assets if a.symbol == symbol), None)
    await message.answer(format_single_asset(symbol, asset), parse_mode="Markdown")


@router.message(Command("crypto"))
async def cmd_crypto(message: Message) -> None:
    assets = await _market_repository().get_latest()
    await message.answer(
        format_asset_class(assets, AssetClass.CRYPTO, "Crypto Market"), parse_mode="Markdown"
    )


@router.message(Command("stocks"))
async def cmd_stocks(message: Message) -> None:
    assets = await _market_repository().get_latest()
    text = "\n\n".join(
        [
            format_asset_class(assets, AssetClass.INDEX, "US Indices"),
            format_asset_class(assets, AssetClass.STOCK, "Magnificent 7"),
        ]
    )
    await message.answer(text, parse_mode="Markdown")


@router.message(Command("macro"))
async def cmd_macro(message: Message) -> None:
    assets = await _market_repository().get_latest()
    await message.answer(
        format_asset_class(assets, AssetClass.MACRO, "Macro Indicators"), parse_mode="Markdown"
    )


@router.message(Command("news"))
async def cmd_news(message: Message) -> None:
    news_repository = NewsRepository(get_session_factory())
    items = await news_repository.get_recent(limit=8)
    await message.answer(format_news(items), parse_mode="Markdown")


@router.message(Command("signals"))
async def cmd_signals(message: Message) -> None:
    session_factory = get_session_factory()
    market_repository = _market_repository()
    news_repository = NewsRepository(session_factory)
    engine = SignalEngine(session_factory, market_repository, news_repository)
    snapshot = await engine.get_latest()
    await message.answer(format_signal(snapshot), parse_mode="Markdown")


@router.message(Command("correlations"))
async def cmd_correlations(message: Message) -> None:
    engine = CorrelationEngine(get_session_factory())
    rows = await engine.get_latest()
    await message.answer(format_correlations(rows), parse_mode="Markdown")


@router.message(Command("report"))
async def cmd_report(message: Message) -> None:
    generator = build_report_generator()
    report = await generator.get_latest()
    if report is None:
        await message.answer(format_report(None), parse_mode="Markdown")
        return

    text = format_report(report)
    # Telegram caps messages at 4096 chars; trim defensively rather than error out.
    await message.answer(text[:4090], parse_mode="Markdown")
