from dataclasses import dataclass

from app.database.models import (
    CryptoHistory,
    ForexHistory,
    MacroHistory,
    MarketHistory,
    StockHistory,
)
from app.services.history.base import HistoricalDataProvider
from app.services.history.providers.coingecko import CoinGeckoHistoricalProvider
from app.services.history.providers.fallback_provider import FallbackHistoricalProvider
from app.services.history.providers.fred import FRED_SERIES, FredHistoricalProvider
from app.services.history.providers.twelvedata_provider import TwelveDataHistoricalProvider
from app.services.history.providers.yfinance_provider import YFinanceHistoricalProvider
from app.services.history.schemas import Timeframe

# Yahoo Finance ticker -> display symbol, grouped the same way as the live
# providers (app/services/market/stocks/provider.py, macro/yfinance_macro.py):
# broad indices live in market_history, individual companies in stock_history.
INDEX_TICKERS: dict[str, str] = {
    "NASDAQ": "^IXIC",
    "SPX": "^GSPC",
    "DJI": "^DJI",
    "RUT": "^RUT",
}
STOCK_TICKERS: dict[str, str] = {
    "AAPL": "AAPL",
    "MSFT": "MSFT",
    "NVDA": "NVDA",
    "TSLA": "TSLA",
    "AMZN": "AMZN",
    "META": "META",
    "GOOGL": "GOOGL",
}
MACRO_YFINANCE_TICKERS: dict[str, str] = {
    "DXY": "DX-Y.NYB",
    "GOLD": "GC=F",
    "SILVER": "SI=F",
}
FOREX_TICKERS: dict[str, str] = {
    "EURUSD": "EURUSD=X",
    "GBPUSD": "GBPUSD=X",
    "USDJPY": "USDJPY=X",
    "USDCHF": "USDCHF=X",
    "AUDUSD": "AUDUSD=X",
    "USDCAD": "USDCAD=X",
}

_ALL_TIMEFRAMES: tuple[Timeframe, ...] = (Timeframe.DAILY, Timeframe.FOUR_HOUR, Timeframe.ONE_HOUR)
_DAILY_ONLY: tuple[Timeframe, ...] = (Timeframe.DAILY,)
# Futures Simulator chart: what the realtime aggregator writes and the
# history API serves -- deliberately NOT part of `timeframes` above, since
# that tuple is what HistorySyncEngine asks the *provider* to fetch, and
# CoinGeckoHistoricalProvider has no 5m/15m support (raises ValueError).
# Mixing the two would make every full sync fail permanently for crypto.
_REALTIME_TIMEFRAMES: tuple[Timeframe, ...] = (Timeframe.FIVE_MINUTE, Timeframe.FIFTEEN_MINUTE)


@dataclass(frozen=True)
class HistorySymbolConfig:
    symbol: str
    model: type
    provider: HistoricalDataProvider
    timeframes: tuple[Timeframe, ...]
    market: str  # "crypto" or "equity" -- used by validation's gap tolerance
    # What the realtime aggregator writes / the history API additionally
    # serves, on top of `timeframes`. Empty for every non-crypto entry.
    realtime_timeframes: tuple[Timeframe, ...] = ()


def build_registry() -> list[HistorySymbolConfig]:
    """The full symbol universe for the Historical Intelligence Engine.

    Excluded and documented in the README: TOTAL market cap and BTC.D (no
    free CoinGecko historical endpoint), and 4h/1h for FRED-sourced macro
    series (FRED has no intraday data).
    """
    # Yahoo Finance has been confirmed (live, via Railway logs) to return
    # empty/malformed responses from this deployment's egress IP -- see
    # AUDIT_REPORT.md. Twelve Data (already configured for the live-quote
    # fallback path) covers individual equities and forex/gold/silver on
    # its free tier; confirmed NOT to cover indices or DXY on that tier
    # ("available starting with the Grow or Venture plan"), so
    # index_provider stays yfinance-only -- no viable free fallback exists
    # for those four symbols today.
    twelvedata_provider = TwelveDataHistoricalProvider()
    index_provider = YFinanceHistoricalProvider(INDEX_TICKERS)
    stock_provider = FallbackHistoricalProvider(
        YFinanceHistoricalProvider(STOCK_TICKERS), twelvedata_provider
    )
    macro_yf_provider = FallbackHistoricalProvider(
        YFinanceHistoricalProvider(MACRO_YFINANCE_TICKERS), twelvedata_provider
    )
    forex_provider = FallbackHistoricalProvider(
        YFinanceHistoricalProvider(FOREX_TICKERS), twelvedata_provider
    )
    crypto_provider = CoinGeckoHistoricalProvider()
    fred_provider = FredHistoricalProvider()

    registry: list[HistorySymbolConfig] = []
    for symbol in INDEX_TICKERS:
        registry.append(
            HistorySymbolConfig(symbol, MarketHistory, index_provider, _ALL_TIMEFRAMES, "equity")
        )
    for symbol in STOCK_TICKERS:
        registry.append(
            HistorySymbolConfig(symbol, StockHistory, stock_provider, _ALL_TIMEFRAMES, "equity")
        )
    # LINK/UNI added for Forecasting 2.0's official daily forecast roster
    # (app/services/forecast/engine.py's OFFICIAL_FORECAST_SYMBOLS); BNB/
    # XRP/DOGE/AVAX/SUI added for the Futures Simulator's 10-symbol
    # supported-asset list -- CoinGeckoHistoricalProvider already supports
    # any symbol in its own COINGECKO_SYMBOL_IDS map, so every addition
    # here is a registry entry, not new provider code.
    for symbol in ("BTC", "ETH", "SOL", "LINK", "UNI", "BNB", "XRP", "DOGE", "AVAX", "SUI"):
        registry.append(
            HistorySymbolConfig(
                symbol,
                CryptoHistory,
                crypto_provider,
                _ALL_TIMEFRAMES,
                "crypto",
                realtime_timeframes=_REALTIME_TIMEFRAMES,
            )
        )
    for symbol in MACRO_YFINANCE_TICKERS:
        registry.append(
            HistorySymbolConfig(symbol, MacroHistory, macro_yf_provider, _ALL_TIMEFRAMES, "equity")
        )
    for symbol in FRED_SERIES:
        registry.append(
            HistorySymbolConfig(symbol, MacroHistory, fred_provider, _DAILY_ONLY, "equity")
        )
    for symbol in FOREX_TICKERS:
        registry.append(
            HistorySymbolConfig(symbol, ForexHistory, forex_provider, _ALL_TIMEFRAMES, "forex")
        )
    return registry


def find_symbol_config(symbol: str) -> HistorySymbolConfig | None:
    """Looks up a symbol's table/provider/timeframes -- shared by every API
    router and Telegram handler that needs to resolve a symbol to its table."""
    symbol = symbol.upper()
    for config in build_registry():
        if config.symbol == symbol:
            return config
    return None
