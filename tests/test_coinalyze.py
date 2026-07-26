from types import SimpleNamespace

import httpx
import pytest
import respx

from app.services.whales.providers.coinalyze import (
    COINALYZE_BASE_URL,
    CoinalyzeClient,
    CoinalyzeError,
)


def _client(api_key: str | None = "fake-key") -> CoinalyzeClient:
    client = CoinalyzeClient()
    client._settings = SimpleNamespace(coinalyze_api_key=api_key, http_timeout_seconds=5.0)
    return client


async def test_raises_when_not_configured():
    client = _client(api_key=None)
    with pytest.raises(CoinalyzeError, match="not configured"):
        await client.get_snapshot("BTC")


@respx.mock
async def test_parses_open_interest_funding_and_liquidations():
    instrument = "BTCUSDT_PERP.A"
    respx.get(f"{COINALYZE_BASE_URL}/open-interest").mock(
        return_value=httpx.Response(200, json=[{"symbol": instrument, "value": 999.5}])
    )
    respx.get(f"{COINALYZE_BASE_URL}/funding-rate").mock(
        return_value=httpx.Response(200, json=[{"symbol": instrument, "value": 0.0003}])
    )
    respx.get(f"{COINALYZE_BASE_URL}/liquidation-history").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "symbol": instrument,
                    "history": [{"t": 1, "l": 100.0, "s": 50.0}, {"t": 2, "l": 25.0, "s": 25.0}],
                }
            ],
        )
    )
    client = _client()

    result = await client.get_snapshot("BTC")

    assert result == {
        "open_interest": 999.5,
        "funding_rate": 0.0003,
        "liquidations_24h": 200.0,
    }


@respx.mock
async def test_never_returns_long_short_ratio():
    instrument = "BTCUSDT_PERP.A"
    respx.get(f"{COINALYZE_BASE_URL}/open-interest").mock(
        return_value=httpx.Response(200, json=[{"symbol": instrument, "value": 1.0}])
    )
    respx.get(f"{COINALYZE_BASE_URL}/funding-rate").mock(return_value=httpx.Response(200, json=[]))
    respx.get(f"{COINALYZE_BASE_URL}/liquidation-history").mock(
        return_value=httpx.Response(200, json=[])
    )
    client = _client()

    result = await client.get_snapshot("BTC")

    assert "long_short_ratio" not in result


@respx.mock
async def test_raises_when_nothing_usable():
    for path in ("/open-interest", "/funding-rate", "/liquidation-history"):
        respx.get(f"{COINALYZE_BASE_URL}{path}").mock(return_value=httpx.Response(200, json=[]))
    client = _client()

    with pytest.raises(CoinalyzeError, match="no usable derivatives data"):
        await client.get_snapshot("BTC")
