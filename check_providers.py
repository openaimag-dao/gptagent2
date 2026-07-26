#!/usr/bin/env python
"""Standalone verification script for the new market-data provider fallback
chains: Twelve Data -> Alpha Vantage -> yfinance for indices/Magnificent 7,
Twelve Data -> yfinance for DXY/Gold/Silver, CoinGlass -> Coinalyze for
crypto derivatives positioning, and Alpha Vantage as a news-sentiment
fallback. Reuses the exact provider classes the live pipeline uses (not a
reimplementation), so what this prints is what the scheduler will actually
see. Requires REDIS_URL to be reachable (used for the providers' cooldown
cache), same as running the bot for real -- fill in .env first.

    python check_providers.py
"""

import asyncio

from app.config import get_settings
from app.services.market.multisource_macro import _SYMBOL_INFO as MACRO_SYMBOL_INFO
from app.services.market.multisource_macro import MultiSourceMacroProvider
from app.services.market.multisource_stocks import _SYMBOL_INFO as STOCK_SYMBOL_INFO
from app.services.market.multisource_stocks import MultiSourceStockProvider
from app.services.market.providers.alphavantage import AlphaVantageClient
from app.services.whales.engine import WhaleIntelligenceEngine
from app.utils.logging import configure_logging

_DERIVATIVES_FIELDS = ("funding_rate", "open_interest", "liquidations_24h", "long_short_ratio")


def _header(title: str) -> None:
    print(f"\n=== {title} ===")


async def _check_quote_provider(title: str, provider, symbol_info: dict) -> tuple[int, int]:
    _header(title)
    try:
        quotes = await provider.fetch()
    except Exception as exc:  # noqa: BLE001 -- report, don't crash the whole run
        print(f"  FAILED to run: {exc}")
        return 0, len(symbol_info)

    by_symbol = {q.symbol: q for q in quotes}
    ok = 0
    for symbol in sorted(symbol_info):
        quote = by_symbol.get(symbol)
        if quote is not None:
            print(f"  {symbol:8s} OK      source={quote.source:12s} price={quote.price}")
            ok += 1
        else:
            print(f"  {symbol:8s} MISSING no source returned data")
    return ok, len(symbol_info)


async def _check_derivatives() -> tuple[int, int]:
    _header("Crypto derivatives positioning (CoinGlass -> Coinalyze)")
    try:
        snapshot = await WhaleIntelligenceEngine().get_snapshot("BTC")
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED to run: {exc}")
        return 0, len(_DERIVATIVES_FIELDS)

    if not snapshot.get("available"):
        print(f"  MISSING {snapshot.get('reason')}")
        return 0, len(_DERIVATIVES_FIELDS)

    print(f"  source={snapshot.get('source')} classification={snapshot.get('classification')}")
    ok = 0
    for field in _DERIVATIVES_FIELDS:
        value = snapshot.get(field)
        if value is not None:
            print(f"  {field:20s} OK      {value}")
            ok += 1
        else:
            print(f"  {field:20s} MISSING")
    return ok, len(_DERIVATIVES_FIELDS)


async def _check_news_sentiment() -> tuple[int, int]:
    _header("Alpha Vantage news sentiment (fallback for RSS News Engine)")
    client = AlphaVantageClient()
    if not client.configured:
        print("  MISSING ALPHAVANTAGE_API_KEY not set")
        return 0, 1
    try:
        items = await client.get_news_sentiment()
    except Exception as exc:  # noqa: BLE001
        print(f"  FAILED to run: {exc}")
        return 0, 1
    if not items:
        print("  MISSING Alpha Vantage returned no usable feed")
        return 0, 1
    first = items[0]
    print(f'  OK      {len(items)} items, e.g. "{first["title"]}" ({first["sentiment_label"]})')
    return 1, 1


async def main() -> None:
    configure_logging()
    settings = get_settings()

    print("Configured keys:")
    for name in (
        "twelvedata_api_key",
        "alphavantage_api_key",
        "coinglass_api_key",
        "coinalyze_api_key",
        "fred_api_key",
    ):
        print(f"  {name}: {'set' if getattr(settings, name) else 'NOT SET'}")

    totals = [
        await _check_quote_provider(
            "Indices & Magnificent 7 (Twelve Data -> Alpha Vantage -> yfinance)",
            MultiSourceStockProvider(),
            STOCK_SYMBOL_INFO,
        ),
        await _check_quote_provider(
            "DXY / Gold / Silver (Twelve Data -> yfinance)",
            MultiSourceMacroProvider(),
            MACRO_SYMBOL_INFO,
        ),
        await _check_derivatives(),
        await _check_news_sentiment(),
    ]

    ok_total = sum(ok for ok, _ in totals)
    field_total = sum(total for _, total in totals)
    _header("Summary")
    print(f"  {ok_total}/{field_total} fields retrieved successfully")


if __name__ == "__main__":
    asyncio.run(main())
