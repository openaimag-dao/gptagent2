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
