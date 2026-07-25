import asyncio
import logging
from datetime import UTC, datetime

import pandas as pd
import yfinance as yf

from app.services.history.base import HistoricalDataProvider
from app.services.history.resample import resample_candles
from app.services.history.schemas import Candle, Timeframe

logger = logging.getLogger(__name__)

# yfinance interval limits, as documented by Yahoo Finance / yfinance itself:
# - "1d" bars: full history available (period="max").
# - "60m" bars: capped by Yahoo at roughly the trailing 730 days, regardless
#   of the requested period.
# There is no native 4h interval; it's resampled from 60m bars here, so 4h
# inherits that same ~730 day cap. See README for the full writeup.
_INTERVAL_BY_TIMEFRAME: dict[Timeframe, str] = {
    Timeframe.DAILY: "1d",
    Timeframe.ONE_HOUR: "60m",
    Timeframe.FOUR_HOUR: "60m",
}
_PERIOD_BY_TIMEFRAME: dict[Timeframe, str] = {
    Timeframe.DAILY: "max",
    Timeframe.ONE_HOUR: "730d",
    Timeframe.FOUR_HOUR: "730d",
}


def _download_sync(ticker: str, timeframe: Timeframe) -> pd.DataFrame:
    return yf.Ticker(ticker).history(
        period=_PERIOD_BY_TIMEFRAME[timeframe],
        interval=_INTERVAL_BY_TIMEFRAME[timeframe],
        auto_adjust=False,
    )


class YFinanceHistoricalProvider(HistoricalDataProvider):
    """Historical daily/hourly candles for indices, equities and yfinance-sourced macro tickers.

    Same known operational limitation as the live YFinanceStockProvider /
    YFinanceMacroProvider: Yahoo Finance may rate-limit or block requests
    from shared/datacenter egress IPs (documented in README).
    """

    name = "yfinance_historical"

    def __init__(self, ticker_by_symbol: dict[str, str]) -> None:
        self._ticker_by_symbol = ticker_by_symbol

    async def fetch_candles(
        self, symbol: str, timeframe: Timeframe, since: datetime | None
    ) -> list[Candle]:
        ticker = self._ticker_by_symbol.get(symbol.upper())
        if ticker is None:
            raise ValueError(f"No Yahoo Finance ticker mapped for symbol {symbol}")

        frame = await asyncio.to_thread(_download_sync, ticker, timeframe)
        if frame.empty:
            return []

        candles = [
            Candle(
                symbol=symbol.upper(),
                timeframe=Timeframe.ONE_HOUR if timeframe == Timeframe.FOUR_HOUR else timeframe,
                timestamp=ts.to_pydatetime().astimezone(UTC),
                open=float(row.Open),
                high=float(row.High),
                low=float(row.Low),
                close=float(row.Close),
                volume=None if pd.isna(row.Volume) else float(row.Volume),
                source=self.name,
            )
            for ts, row in frame.iterrows()
        ]

        if timeframe == Timeframe.FOUR_HOUR:
            candles = resample_candles(candles, Timeframe.FOUR_HOUR)

        if since is not None:
            candles = [c for c in candles if c.timestamp >= since]
        return candles
