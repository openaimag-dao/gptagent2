import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
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


async def _answer(message: Message, text: str) -> None:
    """Sends with Markdown formatting, falling back to plain text.

    Dynamic content (factor names, news titles, LLM-generated report prose)
    can contain characters like a stray "_" or "*" that Telegram's legacy
    Markdown parser treats as an unterminated entity, which raises
    TelegramBadRequest and would otherwise crash the handler.
    """
    try:
        await message.answer(text, parse_mode="Markdown")
    except TelegramBadRequest:
        await message.answer(text)


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

    text = format_report(report)
    # Telegram caps messages at 4096 chars; trim defensively rather than error out.
    await _answer(message, text[:4090])
