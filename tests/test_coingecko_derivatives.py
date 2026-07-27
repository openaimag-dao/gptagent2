from types import SimpleNamespace

import httpx
import pytest
import respx

from app.services.whales.providers.coingecko_derivatives import (
    CoinGeckoDerivativesClient,
    CoinGeckoDerivativesError,
)

_BASE_URL = "https://api.coingecko.com/api/v3"


def _client() -> CoinGeckoDerivativesClient:
    client = CoinGeckoDerivativesClient()
    client._settings = SimpleNamespace(
        coingecko_api_key=None, coingecko_base_url=_BASE_URL, http_timeout_seconds=5.0
    )
    return client


async def test_always_configured():
    assert _client().configured is True


@respx.mock
async def test_picks_highest_open_interest_perpetual_for_symbol():
    respx.get(f"{_BASE_URL}/derivatives").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "index_id": "BTC",
                    "contract_type": "perpetual",
                    "funding_rate": 0.0001,
                    "open_interest": 500.0,
                },
                {
                    "index_id": "BTC",
                    "contract_type": "perpetual",
                    "funding_rate": 0.0007,
                    "open_interest": 999.5,
                },
                {
                    "index_id": "ETH",
                    "contract_type": "perpetual",
                    "funding_rate": 0.0002,
                    "open_interest": 5000.0,
                },
                {
                    "index_id": "BTC",
                    "contract_type": "current_quarter",
                    "funding_rate": None,
                    "open_interest": 10000.0,
                },
            ],
        )
    )
    client = _client()

    result = await client.get_snapshot("BTC")

    assert result == {"funding_rate": 0.0007, "open_interest": 999.5}


@respx.mock
async def test_never_returns_liquidations_or_long_short_ratio():
    respx.get(f"{_BASE_URL}/derivatives").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "index_id": "BTC",
                    "contract_type": "perpetual",
                    "funding_rate": 0.0001,
                    "open_interest": 500.0,
                }
            ],
        )
    )
    client = _client()

    result = await client.get_snapshot("BTC")

    assert "liquidations_24h" not in result
    assert "long_short_ratio" not in result


@respx.mock
async def test_raises_when_no_perpetual_for_symbol():
    respx.get(f"{_BASE_URL}/derivatives").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "index_id": "ETH",
                    "contract_type": "perpetual",
                    "funding_rate": 0.0002,
                    "open_interest": 5000.0,
                }
            ],
        )
    )
    client = _client()

    with pytest.raises(CoinGeckoDerivativesError, match="no perpetual-contract"):
        await client.get_snapshot("BTC")


@respx.mock
async def test_raises_on_http_error():
    respx.get(f"{_BASE_URL}/derivatives").mock(return_value=httpx.Response(500))
    client = _client()

    with pytest.raises(CoinGeckoDerivativesError, match="fetch failed"):
        await client.get_snapshot("BTC")
