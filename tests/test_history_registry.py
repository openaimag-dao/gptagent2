from app.services.history.registry import build_registry
from app.services.history.schemas import Timeframe


def test_registry_has_no_duplicate_symbols():
    registry = build_registry()
    symbols = [c.symbol for c in registry]
    assert len(symbols) == len(set(symbols)), "each symbol should map to exactly one table"


def test_registry_covers_the_expected_symbol_universe():
    registry = build_registry()
    symbols = {c.symbol for c in registry}
    expected = {
        # indices
        "NASDAQ",
        "SPX",
        "DJI",
        "RUT",
        # magnificent 7
        "AAPL",
        "MSFT",
        "NVDA",
        "TSLA",
        "AMZN",
        "META",
        "GOOGL",
        # crypto
        "BTC",
        "ETH",
        "SOL",
        "LINK",
        "UNI",
        # crypto (Futures Simulator's full 10-symbol supported-asset list)
        "BNB",
        "XRP",
        "DOGE",
        "AVAX",
        "SUI",
        # macro
        "DXY",
        "GOLD",
        "SILVER",
        "FEDRATE",
        "VIX",
        "US10Y",
        "US30Y",
        "OIL",
        "CPI",
        "M2",
        # forex
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "USDCHF",
        "AUDUSD",
        "USDCAD",
    }
    assert symbols == expected


def test_fred_backed_macro_symbols_are_daily_only():
    registry = build_registry()
    fred_symbols = {"FEDRATE", "VIX", "US10Y", "US30Y", "OIL", "CPI", "M2"}
    for config in registry:
        if config.symbol in fred_symbols:
            assert config.timeframes == (Timeframe.DAILY,)


def test_every_symbol_declares_a_market_for_gap_tolerance():
    registry = build_registry()
    assert all(c.market in ("crypto", "equity", "forex") for c in registry)


def test_only_crypto_symbols_declare_realtime_timeframes():
    # Futures Simulator chart: 5m/15m are only ever aggregated from the live
    # tick feed for crypto -- CoinGeckoHistoricalProvider (and every other
    # provider) has no support for them, so any non-crypto entry declaring
    # realtime_timeframes would be a lie about what actually gets written.
    registry = build_registry()
    for config in registry:
        if config.market == "crypto":
            assert config.realtime_timeframes == (Timeframe.FIVE_MINUTE, Timeframe.FIFTEEN_MINUTE)
        else:
            assert config.realtime_timeframes == ()


def test_realtime_timeframes_are_never_in_the_syncable_timeframes_tuple():
    # HistorySyncEngine.sync_all iterates config.timeframes and asks the
    # provider to fetch each one -- CoinGeckoHistoricalProvider raises
    # ValueError for 5m/15m, so mixing the two tuples would fail every full
    # sync for crypto, forever.
    registry = build_registry()
    for config in registry:
        assert not (set(config.timeframes) & set(config.realtime_timeframes))
