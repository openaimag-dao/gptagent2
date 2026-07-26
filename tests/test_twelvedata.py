from types import SimpleNamespace

import httpx
import pytest
import respx

from app.services.market.providers.twelvedata import (
    TWELVEDATA_QUOTE_URL,
    TwelveDataClient,
    TwelveDataError,
)


def _client(api_key: str | None = "fake-key") -> TwelveDataClient:
    client = TwelveDataClient()
    client._settings = SimpleNamespace(twelvedata_api_key=api_key, http_timeout_seconds=5.0)
    return client


async def test_raises_when_not_configured():
    client = _client(api_key=None)
    with pytest.raises(TwelveDataError, match="not configured"):
        await client.get_quotes({"NASDAQ": "IXIC"})


async def test_empty_symbol_map_returns_empty():
    client = _client()
    assert await client.get_quotes({}) == {}


@respx.mock
async def test_parses_single_symbol_flat_response():
    respx.get(TWELVEDATA_QUOTE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "symbol": "AAPL",
                "close": "150.0",
                "previous_close": "148.0",
                "volume": "1000",
            },
        )
    )
    client = _client()

    result = await client.get_quotes({"AAPL": "AAPL"})

    assert result == {"AAPL": (150.0, 148.0, 1000.0)}


@respx.mock
async def test_parses_multi_symbol_nested_response():
    respx.get(TWELVEDATA_QUOTE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "IXIC": {"close": "18000.0", "previous_close": "17900.0", "volume": "500"},
                "SPX": {"close": "5000.0", "previous_close": "4950.0", "volume": None},
            },
        )
    )
    client = _client()

    result = await client.get_quotes({"NASDAQ": "IXIC", "SPX": "SPX"})

    assert result == {
        "NASDAQ": (18000.0, 17900.0, 500.0),
        "SPX": (5000.0, 4950.0, None),
    }


@respx.mock
async def test_raises_on_top_level_error_status():
    respx.get(TWELVEDATA_QUOTE_URL).mock(
        return_value=httpx.Response(200, json={"status": "error", "message": "bad key"})
    )
    client = _client()

    with pytest.raises(TwelveDataError, match="bad key"):
        await client.get_quotes({"AAPL": "AAPL"})


@respx.mock
async def test_skips_malformed_entries_and_keeps_the_rest():
    respx.get(TWELVEDATA_QUOTE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "IXIC": {"close": "18000.0", "previous_close": "17900.0", "volume": "500"},
                "SPX": {"status": "error"},
            },
        )
    )
    client = _client()

    result = await client.get_quotes({"NASDAQ": "IXIC", "SPX": "SPX"})

    assert result == {"NASDAQ": (18000.0, 17900.0, 500.0)}


@respx.mock
async def test_raises_when_nothing_usable_came_back():
    respx.get(TWELVEDATA_QUOTE_URL).mock(
        return_value=httpx.Response(200, json={"IXIC": {"status": "error"}})
    )
    client = _client()

    with pytest.raises(TwelveDataError, match="no usable quotes"):
        await client.get_quotes({"NASDAQ": "IXIC"})


@respx.mock
async def test_raises_on_http_error():
    respx.get(TWELVEDATA_QUOTE_URL).mock(return_value=httpx.Response(429))
    client = _client()

    with pytest.raises(TwelveDataError):
        await client.get_quotes({"AAPL": "AAPL"})
