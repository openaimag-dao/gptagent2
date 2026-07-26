from types import SimpleNamespace

import httpx
import pytest
import respx

from app.services.whales.providers.coinglass import (
    COINGLASS_BASE_URL,
    CoinGlassClient,
    CoinGlassError,
)


def _client(api_key: str | None = "fake-key") -> CoinGlassClient:
    client = CoinGlassClient()
    client._settings = SimpleNamespace(coinglass_api_key=api_key, http_timeout_seconds=5.0)
    return client


async def test_raises_when_not_configured():
    client = _client(api_key=None)
    with pytest.raises(CoinGlassError, match="not configured"):
        await client.get_snapshot("BTC")


@respx.mock
async def test_parses_markets_and_liquidations():
    respx.get(f"{COINGLASS_BASE_URL}/api/futures/coins-markets").mock(
        return_value=httpx.Response(
            200,
            json={
                "code": "0",
                "data": [
                    {
                        "symbol": "BTC",
                        "fundingRate": 0.0001,
                        "openInterest": 12345.6,
                        "longShortRatio": 1.2,
                    }
                ],
            },
        )
    )
    respx.get(f"{COINGLASS_BASE_URL}/api/futures/liquidation/coin-list").mock(
        return_value=httpx.Response(
            200,
            json={"code": "0", "data": [{"symbol": "BTC", "liquidationUsd24h": 5000000.0}]},
        )
    )
    client = _client()

    result = await client.get_snapshot("BTC")

    assert result == {
        "funding_rate": 0.0001,
        "open_interest": 12345.6,
        "long_short_ratio": 1.2,
        "liquidations_24h": 5000000.0,
    }


@respx.mock
async def test_raises_when_success_false():
    respx.get(f"{COINGLASS_BASE_URL}/api/futures/coins-markets").mock(
        return_value=httpx.Response(200, json={"success": False, "msg": "API key missing."})
    )
    respx.get(f"{COINGLASS_BASE_URL}/api/futures/liquidation/coin-list").mock(
        return_value=httpx.Response(200, json={"success": False, "msg": "API key missing."})
    )
    client = _client()

    with pytest.raises(CoinGlassError, match="no usable derivatives data"):
        await client.get_snapshot("BTC")


@respx.mock
async def test_symbol_not_found_leaves_result_empty_and_raises():
    respx.get(f"{COINGLASS_BASE_URL}/api/futures/coins-markets").mock(
        return_value=httpx.Response(200, json={"code": "0", "data": [{"symbol": "ETH"}]})
    )
    respx.get(f"{COINGLASS_BASE_URL}/api/futures/liquidation/coin-list").mock(
        return_value=httpx.Response(200, json={"code": "0", "data": [{"symbol": "ETH"}]})
    )
    client = _client()

    with pytest.raises(CoinGlassError):
        await client.get_snapshot("BTC")


@respx.mock
async def test_partial_data_still_returned():
    respx.get(f"{COINGLASS_BASE_URL}/api/futures/coins-markets").mock(
        return_value=httpx.Response(
            200, json={"code": "0", "data": [{"symbol": "BTC", "fundingRate": 0.0002}]}
        )
    )
    respx.get(f"{COINGLASS_BASE_URL}/api/futures/liquidation/coin-list").mock(
        return_value=httpx.Response(500)
    )
    client = _client()

    result = await client.get_snapshot("BTC")

    assert result == {"funding_rate": 0.0002}
