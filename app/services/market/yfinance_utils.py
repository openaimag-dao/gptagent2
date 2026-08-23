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


async def download_last_two_closes(tickers: list[str], attempts: int = 2) -> BarsBySymbol:
    """Async wrapper with retries that accumulate partial results.

    yfinance swallows per-ticker failures internally (logs a warning, returns
    partial data for the rest) rather than raising. The previous version of
    this function only retried when the *whole* batch came back empty, so a
    single ticker rate-limited alongside others that succeeded was dropped
    permanently after attempt 1 -- it never got a second chance just because
    its batch-mates happened to succeed. This version re-requests only the
    tickers still missing on each attempt and accumulates results, so a
    ticker gets up to `attempts` real chances regardless of what happens to
    the rest of the batch.

    Default lowered from 4 to 2: production logs (this is the last-resort
    fallback in multisource_stocks.py/multisource_macro.py, tried only after
    Twelve Data and Alpha Vantage both fail) show every index/macro ticker
    failing identically on every attempt with an empty-body JSONDecodeError
    -- the same signature as an anti-bot/cloud-IP block, not a transient
    rate limit (see coinbase_client.py's docstring for the same failure
    class already diagnosed and worked around for Binance in this project).
    4 attempts burned ~159s of every 5-minute collection cycle for a call
    that never once succeeded; retries never helped, they only delayed the
    job. 2 keeps one real second chance for a genuinely transient blip
    without paying for two more guaranteed-to-fail rounds.
    """
    accumulated: BarsBySymbol = {}
    remaining = list(tickers)
    for attempt in range(1, attempts + 1):
        if not remaining:
            break
        batch = await asyncio.to_thread(download_last_two_closes_sync, remaining)
        accumulated.update(batch)
        remaining = [t for t in remaining if t not in accumulated]
        if remaining and attempt < attempts:
            logger.warning(
                "yfinance batch download missing %d/%d tickers (%s), retrying (attempt %d/%d)",
                len(remaining),
                len(tickers),
                ", ".join(remaining),
                attempt,
                attempts,
            )
            await asyncio.sleep(3 * attempt)
    return accumulated


__all__ = ["download_last_two_closes", "download_last_two_closes_sync"]
