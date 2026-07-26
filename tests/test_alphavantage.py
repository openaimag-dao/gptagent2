from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest
import respx

from app.services.market.providers.alphavantage import (
    ALPHAVANTAGE_URL,
    AlphaVantageClient,
    AlphaVantageError,
)


def _client(api_key: str | None = "fake-key") -> AlphaVantageClient:
    client = AlphaVantageClient()
    client._settings = SimpleNamespace(alphavantage_api_key=api_key, http_timeout_seconds=5.0)
    return client


async def test_get_quotes_raises_when_not_configured():
    client = _client(api_key=None)
    with pytest.raises(AlphaVantageError, match="not configured"):
        await client.get_quotes(["AAPL"])


async def test_get_quotes_empty_list_returns_empty():
    client = _client()
    assert await client.get_quotes([]) == {}


async def test_get_news_sentiment_returns_none_when_not_configured():
    client = _client(api_key=None)
    assert await client.get_news_sentiment() is None


@respx.mock
async def test_get_quotes_parses_global_quote():
    respx.get(ALPHAVANTAGE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "Global Quote": {
                    "05. price": "150.00",
                    "08. previous close": "148.00",
                    "06. volume": "1000",
                }
            },
        )
    )
    client = _client()

    result = await client.get_quotes(["AAPL"])

    assert result == {"AAPL": (150.0, 148.0, 1000.0)}


@respx.mock
async def test_get_quotes_skips_symbols_with_no_data():
    respx.get(ALPHAVANTAGE_URL).mock(return_value=httpx.Response(200, json={}))
    client = _client()

    with pytest.raises(AlphaVantageError, match="no usable quotes"):
        await client.get_quotes(["AAPL"])


@respx.mock
async def test_get_quotes_respects_rate_limit_spacing_between_symbols():
    respx.get(ALPHAVANTAGE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "Global Quote": {
                    "05. price": "1.0",
                    "08. previous close": "1.0",
                    "06. volume": "1",
                }
            },
        )
    )
    client = _client()

    with patch("app.services.market.providers.alphavantage.asyncio.sleep") as mock_sleep:
        result = await client.get_quotes(["AAPL", "MSFT", "NVDA"])

    assert set(result) == {"AAPL", "MSFT", "NVDA"}
    # 3 symbols -> 2 inter-call delays, not before the first call
    assert mock_sleep.await_count == 2
    mock_sleep.assert_awaited_with(12.0)


@respx.mock
async def test_get_news_sentiment_parses_feed():
    respx.get(ALPHAVANTAGE_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "feed": [
                    {
                        "title": "Fed holds rates",
                        "url": "https://example.com/1",
                        "overall_sentiment_score": 0.3,
                        "overall_sentiment_label": "Somewhat-Bullish",
                    }
                ]
            },
        )
    )
    client = _client()

    result = await client.get_news_sentiment()

    assert result == [
        {
            "title": "Fed holds rates",
            "url": "https://example.com/1",
            "sentiment_score": 0.3,
            "sentiment_label": "Somewhat-Bullish",
        }
    ]


@respx.mock
async def test_get_news_sentiment_returns_none_on_empty_feed():
    respx.get(ALPHAVANTAGE_URL).mock(return_value=httpx.Response(200, json={"feed": []}))
    client = _client()

    assert await client.get_news_sentiment() is None
