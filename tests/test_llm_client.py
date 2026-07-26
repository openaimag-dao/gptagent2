from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from anthropic import APIError

from app.llm.client import generate_analysis_json


def _settings(anthropic_api_key: str | None, openai_api_key: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        anthropic_api_key=anthropic_api_key,
        anthropic_model="claude-sonnet-4-5-20250929",
        openai_api_key=openai_api_key,
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-4o-mini",
    )


def _api_error(message: str = "boom") -> APIError:
    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    return APIError(message, request, body=None)


async def test_raises_when_neither_provider_configured():
    with patch("app.llm.client.get_settings", return_value=_settings(None, None)):
        with pytest.raises(RuntimeError, match="Neither ANTHROPIC_API_KEY nor OPENAI_API_KEY"):
            await generate_analysis_json("system", "user")


async def test_uses_anthropic_when_configured():
    with (
        patch("app.llm.client.get_settings", return_value=_settings("claude-key", "sk-openai")),
        patch(
            "app.llm.client._anthropic_completion", new=AsyncMock(return_value='{"a": 1}')
        ) as anthropic_call,
        patch("app.llm.client._openai_completion", new=AsyncMock()) as openai_call,
    ):
        result = await generate_analysis_json("system", "user")

    assert result == '{"a": 1}'
    anthropic_call.assert_awaited_once_with("system", "user")
    openai_call.assert_not_called()


async def test_uses_openai_when_anthropic_not_configured():
    with (
        patch("app.llm.client.get_settings", return_value=_settings(None, "sk-openai")),
        patch("app.llm.client._anthropic_completion", new=AsyncMock()) as anthropic_call,
        patch(
            "app.llm.client._openai_completion", new=AsyncMock(return_value='{"b": 2}')
        ) as openai_call,
    ):
        result = await generate_analysis_json("system", "user")

    assert result == '{"b": 2}'
    anthropic_call.assert_not_called()
    openai_call.assert_awaited_once_with("system", "user")


async def test_falls_back_to_openai_when_anthropic_fails_and_openai_configured():
    with (
        patch("app.llm.client.get_settings", return_value=_settings("claude-key", "sk-openai")),
        patch("app.llm.client._anthropic_completion", new=AsyncMock(side_effect=_api_error())),
        patch(
            "app.llm.client._openai_completion", new=AsyncMock(return_value='{"fallback": true}')
        ) as openai_call,
    ):
        result = await generate_analysis_json("system", "user")

    assert result == '{"fallback": true}'
    openai_call.assert_awaited_once_with("system", "user")


async def test_raises_when_anthropic_fails_and_no_openai_configured():
    with (
        patch("app.llm.client.get_settings", return_value=_settings("claude-key", None)),
        patch(
            "app.llm.client._anthropic_completion",
            new=AsyncMock(side_effect=_api_error("rate limited")),
        ),
    ):
        with pytest.raises(RuntimeError, match="Anthropic report generation failed"):
            await generate_analysis_json("system", "user")
