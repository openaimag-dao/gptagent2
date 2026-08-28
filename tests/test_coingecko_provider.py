from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
import respx

from app.services.history.providers.coingecko import CoinGeckoHistoricalProvider
from app.services.history.schemas import Timeframe

_BASE_URL = "https://api.coingecko.com/api/v3"


def _provider() -> CoinGeckoHistoricalProvider:
    provider = CoinGeckoHistoricalProvider()
    provider._settings = SimpleNamespace(
        coingecko_api_key=None, coingecko_base_url=_BASE_URL, http_timeout_seconds=5.0
    )
    return provider


@respx.mock
async def test_thirty_minute_uses_the_ohlc_endpoint_with_a_valid_enum_days_value():
    # CoinGecko's free-tier /ohlc `days` param is an enum {1, 7, 14, 30, 90,
    # 180, 365, max}, not a free-form integer -- days=2 (which would also
    # land in the 30-minutely granularity bucket) 400s because it isn't one
    # of the accepted values. Only `1` is both in the enum and in that bucket.
    route = respx.get(f"{_BASE_URL}/coins/bitcoin/ohlc").mock(
        return_value=httpx.Response(200, json=[[1735689600000, 100.0, 110.0, 95.0, 105.0]])
    )

    await _provider().fetch_candles("BTC", Timeframe.THIRTY_MINUTE, None)

    assert route.calls.call_count == 1
    assert route.calls.last.request.url.params["days"] == "1"


@respx.mock
async def test_four_day_uses_the_ohlc_endpoint_with_the_365_day_window():
    route = respx.get(f"{_BASE_URL}/coins/bitcoin/ohlc").mock(
        return_value=httpx.Response(200, json=[[1735689600000, 100.0, 110.0, 95.0, 105.0]])
    )

    await _provider().fetch_candles("BTC", Timeframe.FOUR_DAY, None)

    assert route.calls.call_count == 1
    assert route.calls.last.request.url.params["days"] == "365"


@respx.mock
async def test_ohlc_timestamp_is_shifted_from_close_time_to_open_time():
    # CoinGecko's /ohlc timestamps mark each candle's CLOSE time; this
    # project's Candle.timestamp convention is the candle's OPEN time (see
    # the schema's own docstring), so fetch_candles must shift it back by
    # one candle's duration -- here, 30 minutes.
    close_ts_ms = 1735689600000  # 2025-01-01T00:00:00Z
    respx.get(f"{_BASE_URL}/coins/bitcoin/ohlc").mock(
        return_value=httpx.Response(200, json=[[close_ts_ms, 100.0, 110.0, 95.0, 105.0]])
    )

    candles = await _provider().fetch_candles("BTC", Timeframe.THIRTY_MINUTE, None)

    assert len(candles) == 1
    close_time = datetime.fromtimestamp(close_ts_ms / 1000, tz=UTC)
    assert candles[0].timestamp == close_time - timedelta(minutes=30)


@respx.mock
async def test_ohlc_candles_carry_real_high_low_and_no_volume():
    respx.get(f"{_BASE_URL}/coins/bitcoin/ohlc").mock(
        return_value=httpx.Response(200, json=[[1735689600000, 100.0, 110.0, 95.0, 105.0]])
    )

    candles = await _provider().fetch_candles("BTC", Timeframe.THIRTY_MINUTE, None)

    assert len(candles) == 1
    c = candles[0]
    assert c.open == 100.0
    assert c.high == 110.0
    assert c.low == 95.0
    assert c.close == 105.0
    assert c.high != c.low  # real wick, unlike /market_chart's flat candles
    assert c.volume is None  # /ohlc has no volume field -- never fabricated
    assert c.source == "coingecko_historical"
    assert c.timeframe == Timeframe.THIRTY_MINUTE


@respx.mock
async def test_ohlc_candles_are_filtered_by_since():
    since = datetime(2025, 1, 10, tzinfo=UTC)
    # FOUR_DAY candles are 4 days long; timestamps below are CLOSE times
    # (the raw /ohlc convention), so each candle's shifted-back OPEN time is
    # 4 days earlier than the close time given here.
    old_close = datetime(2025, 1, 10, tzinfo=UTC)  # opens 2025-01-06, before `since`
    new_close = datetime(2025, 1, 20, tzinfo=UTC)  # opens 2025-01-16, after `since`
    respx.get(f"{_BASE_URL}/coins/bitcoin/ohlc").mock(
        return_value=httpx.Response(
            200,
            json=[
                [int(old_close.timestamp() * 1000), 100.0, 110.0, 95.0, 105.0],
                [int(new_close.timestamp() * 1000), 105.0, 115.0, 100.0, 110.0],
            ],
        )
    )

    candles = await _provider().fetch_candles("BTC", Timeframe.FOUR_DAY, since)

    assert len(candles) == 1
    assert candles[0].close == 110.0


async def test_unsupported_timeframe_still_raises():
    with pytest.raises(ValueError, match="Unsupported timeframe"):
        await _provider().fetch_candles("BTC", Timeframe.FIVE_MINUTE, None)
