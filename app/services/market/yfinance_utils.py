import asyncio
import logging

import yfinance as yf

logger = logging.getLogger(__name__)


BarsBySymbol = dict[str, tuple[float, float, float | None]]


def download_last_two_closes_sync(tickers: list[str]) -> BarsBySymbol:
    """Blocking yfinance batch download.

    Returns {ticker: (last_close, previous_close, last_volume)}. Tickers with
    insufficient history are omitted rather than raising, so one bad symbol
    never breaks the whole batch.
    """
    data = yf.download(
        tickers=tickers,
        period="5d",
        interval="1d",
        group_by="ticker",
        auto_adjust=False,
        progress=False,
        threads=True,
    )

    results: BarsBySymbol = {}
    for ticker in tickers:
        try:
            frame = data[ticker] if len(tickers) > 1 else data
            closes = frame["Close"].dropna()
            volumes = frame["Volume"].dropna()
        except KeyError:
            logger.warning("No data returned for ticker %s", ticker)
            continue

        if len(closes) < 2:
            logger.warning("Insufficient price history for ticker %s", ticker)
            continue

        last_close = float(closes.iloc[-1])
        prev_close = float(closes.iloc[-2])
        last_volume = float(volumes.iloc[-1]) if len(volumes) else None
        results[ticker] = (last_close, prev_close, last_volume)

    return results


async def download_last_two_closes(tickers: list[str], attempts: int = 3) -> BarsBySymbol:
    """Async wrapper with retries.

    yfinance swallows per-ticker failures internally (logs a warning, returns
    partial data) rather than raising, so a plain exception retry wouldn't
    help. Instead we retry the whole batch when it comes back completely
    empty -- the signature of a transient rate limit or network blip -- and
    accept partial results otherwise.
    """
    last_result: BarsBySymbol = {}
    for attempt in range(1, attempts + 1):
        last_result = await asyncio.to_thread(download_last_two_closes_sync, tickers)
        if last_result:
            return last_result
        if attempt < attempts:
            logger.warning(
                "yfinance batch download returned no data, retrying (attempt %d/%d)",
                attempt,
                attempts,
            )
            await asyncio.sleep(2 * attempt)
    return last_result


__all__ = ["download_last_two_closes", "download_last_two_closes_sync"]
