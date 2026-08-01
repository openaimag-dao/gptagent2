from unittest.mock import AsyncMock, patch

from app.services.market.multisource_macro import MultiSourceMacroProvider
from app.services.market.multisource_stocks import MultiSourceStockProvider
from app.services.market.providers.twelvedata import TwelveDataError


def _provider_with_fake_cache(provider_cls, **kwargs) -> object:
    """Builds a provider with real client objects (so `.configured` behaves
    normally) but fake Redis-cache objects, avoiding any real Redis
    connection in these unit tests."""
    provider = provider_cls(**kwargs)
    provider._td_cache = AsyncMock()
    provider._td_cache.get.return_value = None
    if hasattr(provider, "_av_cache"):
        provider._av_cache = AsyncMock()
        provider._av_cache.get.return_value = None
    return provider


async def test_stock_provider_uses_twelvedata_when_it_succeeds():
    twelvedata = AsyncMock()
    twelvedata.configured = True
    # Two independent calls now (indices, then Magnificent 7) -- see
    # multisource_stocks.py's module docstring for why they're split.
    twelvedata.get_quotes.side_effect = [
        {"NASDAQ": (18000.0, 17900.0, 500.0)},
        {"AAPL": (150.0, 148.0, 1000.0)},
    ]
    provider = _provider_with_fake_cache(
        MultiSourceStockProvider, twelvedata=twelvedata, alphavantage=AsyncMock(configured=False)
    )

    with (
        patch(
            "app.services.market.multisource_stocks.download_last_two_closes",
            new=AsyncMock(return_value={}),
        ),
        patch("app.services.market.multisource_stocks.asyncio.sleep", new=AsyncMock()),
    ):
        quotes = await provider.fetch()

    by_symbol = {q.symbol: q for q in quotes}
    assert by_symbol["NASDAQ"].source == "twelvedata"
    assert by_symbol["NASDAQ"].price == 18000.0
    assert by_symbol["AAPL"].source == "twelvedata"
    # symbols Twelve Data didn't return and yfinance mock returned nothing for
    # should simply be absent, not crash the whole fetch
    assert "SPX" not in by_symbol
    assert twelvedata.get_quotes.await_count == 2


async def test_stock_provider_staggers_magnificent_seven_call_away_from_indices():
    twelvedata = AsyncMock()
    twelvedata.configured = True
    twelvedata.get_quotes.side_effect = [
        {"NASDAQ": (18000.0, 17900.0, 500.0)},
        {"AAPL": (150.0, 148.0, 1000.0)},
    ]
    provider = _provider_with_fake_cache(
        MultiSourceStockProvider, twelvedata=twelvedata, alphavantage=AsyncMock(configured=False)
    )

    with (
        patch(
            "app.services.market.multisource_stocks.download_last_two_closes",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "app.services.market.multisource_stocks.asyncio.sleep", new=AsyncMock()
        ) as sleep_mock,
    ):
        await provider.fetch()

    # Only the Magnificent 7 call is staggered -- the 4-credit indices call
    # fires immediately since it's already well under Twelve Data's
    # 8-credit/minute cap on its own.
    sleep_mock.assert_awaited_once()
    requested_symbols = [call.args[0] for call in twelvedata.get_quotes.await_args_list]
    assert "NASDAQ" in requested_symbols[0]
    assert "AAPL" in requested_symbols[1]


async def test_stock_provider_falls_back_to_alphavantage_for_missing_mag7():
    twelvedata = AsyncMock()
    twelvedata.configured = True
    # Indices succeed (4 credits, under budget); Magnificent 7 still fails
    # (e.g. Twelve Data still rate-limited for other reasons) -- Alpha
    # Vantage should cover the gap.
    twelvedata.get_quotes.side_effect = [
        {"NASDAQ": (18000.0, 17900.0, 500.0)},
        TwelveDataError("rate limited"),
    ]

    alphavantage = AsyncMock()
    alphavantage.configured = True
    alphavantage.get_quotes.return_value = {"AAPL": (150.0, 148.0, 1000.0)}

    provider = _provider_with_fake_cache(
        MultiSourceStockProvider, twelvedata=twelvedata, alphavantage=alphavantage
    )

    with (
        patch(
            "app.services.market.multisource_stocks.download_last_two_closes",
            new=AsyncMock(return_value={}),
        ),
        patch("app.services.market.multisource_stocks.asyncio.sleep", new=AsyncMock()),
    ):
        quotes = await provider.fetch()

    by_symbol = {q.symbol: q for q in quotes}
    assert by_symbol["NASDAQ"].source == "twelvedata"
    assert by_symbol["AAPL"].source == "alphavantage"
    # Alpha Vantage should only ever be asked for Magnificent 7 tickers,
    # never index symbols like SPX/DJI/RUT/NASDAQ.
    requested = alphavantage.get_quotes.await_args.args[0]
    assert set(requested).issubset({"AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOGL"})


async def test_stock_provider_falls_back_to_yfinance_when_everything_else_fails():
    twelvedata = AsyncMock()
    twelvedata.configured = False
    alphavantage = AsyncMock()
    alphavantage.configured = False

    provider = _provider_with_fake_cache(
        MultiSourceStockProvider, twelvedata=twelvedata, alphavantage=alphavantage
    )

    with patch(
        "app.services.market.multisource_stocks.download_last_two_closes",
        new=AsyncMock(return_value={"^IXIC": (18000.0, 17900.0, 500.0)}),
    ):
        quotes = await provider.fetch()

    by_symbol = {q.symbol: q for q in quotes}
    assert by_symbol["NASDAQ"].source == "yfinance"


async def test_stock_provider_uses_cached_twelvedata_result_without_calling_client():
    twelvedata = AsyncMock()
    twelvedata.configured = True
    provider = _provider_with_fake_cache(
        MultiSourceStockProvider, twelvedata=twelvedata, alphavantage=AsyncMock(configured=False)
    )
    provider._td_cache.get.return_value = {"NASDAQ": [18000.0, 17900.0, 500.0]}

    with patch(
        "app.services.market.multisource_stocks.download_last_two_closes",
        new=AsyncMock(return_value={}),
    ):
        quotes = await provider.fetch()

    twelvedata.get_quotes.assert_not_called()
    by_symbol = {q.symbol: q for q in quotes}
    assert by_symbol["NASDAQ"].source == "twelvedata"


async def test_stock_provider_survives_twelvedata_error():
    twelvedata = AsyncMock()
    twelvedata.configured = True
    twelvedata.get_quotes.side_effect = TwelveDataError("rate limited")
    provider = _provider_with_fake_cache(
        MultiSourceStockProvider, twelvedata=twelvedata, alphavantage=AsyncMock(configured=False)
    )

    with (
        patch(
            "app.services.market.multisource_stocks.download_last_two_closes",
            new=AsyncMock(return_value={"^IXIC": (18000.0, 17900.0, 500.0)}),
        ),
        patch("app.services.market.multisource_stocks.asyncio.sleep", new=AsyncMock()),
    ):
        quotes = await provider.fetch()

    by_symbol = {q.symbol: q for q in quotes}
    assert by_symbol["NASDAQ"].source == "yfinance"


async def test_macro_provider_prefers_twelvedata_then_yfinance():
    twelvedata = AsyncMock()
    twelvedata.configured = True
    twelvedata.get_quotes.return_value = {"DXY": (104.0, 103.5, None)}
    provider = _provider_with_fake_cache(MultiSourceMacroProvider, twelvedata=twelvedata)

    with (
        patch(
            "app.services.market.multisource_macro.download_last_two_closes",
            new=AsyncMock(return_value={"GC=F": (2000.0, 1990.0, 100.0)}),
        ),
        patch("app.services.market.multisource_macro.asyncio.sleep", new=AsyncMock()) as sleep_mock,
    ):
        quotes = await provider.fetch()

    by_symbol = {q.symbol: q for q in quotes}
    assert by_symbol["DXY"].source == "twelvedata"
    assert by_symbol["GOLD"].source == "yfinance"
    assert by_symbol["GOLD"].price == 2000.0
    # Stagger delay must fire before the real Twelve Data call on a cache
    # miss -- this is what keeps it out of the stocks provider's per-minute
    # credit window (see the module docstring for why).
    sleep_mock.assert_awaited_once()


async def test_macro_provider_skips_stagger_delay_on_cache_hit():
    twelvedata = AsyncMock()
    twelvedata.configured = True
    provider = _provider_with_fake_cache(MultiSourceMacroProvider, twelvedata=twelvedata)
    provider._td_cache.get.return_value = {"DXY": [104.0, 103.5, None]}

    with (
        patch(
            "app.services.market.multisource_macro.download_last_two_closes",
            new=AsyncMock(return_value={}),
        ),
        patch("app.services.market.multisource_macro.asyncio.sleep", new=AsyncMock()) as sleep_mock,
    ):
        quotes = await provider.fetch()

    twelvedata.get_quotes.assert_not_called()
    sleep_mock.assert_not_awaited()
    by_symbol = {q.symbol: q for q in quotes}
    assert by_symbol["DXY"].source == "twelvedata"
