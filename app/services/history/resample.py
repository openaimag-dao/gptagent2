import pandas as pd

from app.services.history.schemas import Candle, Timeframe

_RULE_BY_TIMEFRAME: dict[Timeframe, str] = {
    Timeframe.FOUR_HOUR: "4h",
    Timeframe.FIFTEEN_MINUTE: "15min",
}


def resample_candles(candles: list[Candle], target: Timeframe) -> list[Candle]:
    """Aggregates finer-grained candles (e.g. 1h) up into a coarser timeframe (e.g. 4h).

    Bars with no source data in a given bucket produce NaN OHLC on aggregation
    and are dropped, rather than fabricating a flat/zero candle for a period
    the market had no activity in.
    """
    if not candles:
        return []

    rule = _RULE_BY_TIMEFRAME[target]
    frame = (
        pd.DataFrame(
            {
                "timestamp": [c.timestamp for c in candles],
                "open": [c.open for c in candles],
                "high": [c.high for c in candles],
                "low": [c.low for c in candles],
                "close": [c.close for c in candles],
                "volume": [c.volume for c in candles],
            }
        )
        .set_index("timestamp")
        .sort_index()
    )

    # min_count=1 on the volume sum: a bucket with zero real (non-null)
    # volume observations sums to NaN (-> None below), not 0 -- pandas'
    # default sum() of an all-NaN group is 0.0, which would silently turn
    # "we don't have volume data" (the realtime-aggregated 5m candles this
    # feeds 15m from -- see app/services/realtime/aggregator.py) into a
    # fabricated "confirmed zero volume" claim.
    resampled = frame.resample(rule).agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": lambda s: s.sum(min_count=1),
        }
    )
    resampled = resampled.dropna(subset=["open", "high", "low", "close"])

    symbol = candles[0].symbol
    source = candles[0].source
    return [
        Candle(
            symbol=symbol,
            timeframe=target,
            timestamp=ts.to_pydatetime(),
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=None if pd.isna(row.volume) else float(row.volume),
            source=source,
        )
        for ts, row in resampled.iterrows()
    ]
