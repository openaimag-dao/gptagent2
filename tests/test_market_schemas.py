from app.services.market.schemas import AssetClass, AssetQuote


def test_asset_quote_defaults():
    quote = AssetQuote(
        symbol="btc",
        name="Bitcoin",
        asset_class=AssetClass.CRYPTO,
        price=65000.5,
        source="coingecko",
    )

    assert quote.symbol == "btc"
    assert quote.change_24h is None
    assert quote.change_pct_24h is None
    assert quote.extra == {}


def test_asset_quote_accepts_string_asset_class():
    quote = AssetQuote(
        symbol="AAPL",
        name="Apple",
        asset_class="stock",
        price=210.42,
        source="yfinance_stocks",
    )

    assert quote.asset_class is AssetClass.STOCK
