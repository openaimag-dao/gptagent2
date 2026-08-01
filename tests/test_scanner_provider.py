from unittest.mock import AsyncMock, patch

from app.services.scanner.provider import CoinGeckoMarketsClient


def _client() -> CoinGeckoMarketsClient:
    with patch("app.services.scanner.provider.get_settings") as mock_settings:
        mock_settings.return_value.coingecko_api_key = None
        mock_settings.return_value.coingecko_base_url = "https://api.coingecko.com/api/v3"
        mock_settings.return_value.http_timeout_seconds = 15.0
        return CoinGeckoMarketsClient()


async def test_fetch_top_paginates_full_pages():
    client = _client()
    page1 = [{"id": f"coin{i}"} for i in range(250)]
    page2 = [{"id": f"coin{i}"} for i in range(250, 300)]
    client._get = AsyncMock(side_effect=[page1, page2])

    result = await client.fetch_top(300)

    assert len(result) == 300
    assert client._get.call_count == 2


async def test_fetch_top_stops_on_empty_page():
    client = _client()
    client._get = AsyncMock(side_effect=[[{"id": "a"}], []])

    result = await client.fetch_top(500)

    assert len(result) == 1


async def test_fetch_top_truncates_to_requested_limit():
    client = _client()
    client._get = AsyncMock(return_value=[{"id": f"coin{i}"} for i in range(250)])

    result = await client.fetch_top(10)

    assert len(result) == 10


async def test_fetch_by_ids_empty_list_short_circuits():
    client = _client()
    client._get = AsyncMock()

    result = await client.fetch_by_ids([])

    assert result == []
    client._get.assert_not_called()


async def test_fetch_by_ids_calls_get_with_joined_ids():
    client = _client()
    client._get = AsyncMock(return_value=[{"id": "bitcoin"}])

    result = await client.fetch_by_ids(["bitcoin", "ethereum"])

    assert result == [{"id": "bitcoin"}]
    args, _kwargs = client._get.call_args
    assert args[1]["ids"] == "bitcoin,ethereum"


def test_headers_include_api_key_when_configured():
    with patch("app.services.scanner.provider.get_settings") as mock_settings:
        mock_settings.return_value.coingecko_api_key = "secret"
        mock_settings.return_value.coingecko_base_url = "https://api.coingecko.com/api/v3"
        mock_settings.return_value.http_timeout_seconds = 15.0
        client = CoinGeckoMarketsClient()
    assert client._headers() == {"x-cg-demo-api-key": "secret"}


def test_headers_empty_when_not_configured():
    client = _client()
    assert client._headers() == {}
